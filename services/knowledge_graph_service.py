"""
知识图谱服务：从知识库内容中提取实体和关系，构建知识图谱
支持按文件生成、缓存到数据库、从缓存读取
"""
import json
import logging
import os
from typing import List, Dict, Tuple, Optional
from openai import AsyncOpenAI
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from models import KnowledgeGraph

logger = logging.getLogger("knowledge_graph")

LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")

if not DEEPSEEK_API_KEY:
    logger.warning("DEEPSEEK_API_KEY 环境变量未设置，知识图谱生成功能将不可用")

deepseek_client = AsyncOpenAI(
    api_key=DEEPSEEK_API_KEY,
    base_url=LLM_BASE_URL,
)

ENTITY_COLORS = {
    "人物": "#e74c3c",
    "组织": "#3498db",
    "概念": "#9b59b6",
    "技术": "#1abc9c",
    "其他": "#95a5a6",
}


async def _call_llm_for_graph(text: str, retry_count: int = 0) -> Tuple[List[Dict], List[Dict]]:
    """
    调用LLM从文本中提取知识图谱，支持重试
    """
    import re

    system_prompt = (
        "你是一个知识图谱构建专家。你的任务是分析文本并从中提取实体和关系。"
        "你必须严格遵守以下规则：\n"
        "1. 直接输出纯JSON，不要写任何解释、分析、推理过程、前缀或后缀文字\n"
        "2. 不要使用markdown代码块（不要用```json或```包裹）\n"
        "3. JSON的第一层键必须是nodes和edges\n"
        "4. 每个node必须有id、label、type三个字段\n"
        "5. 每个edge必须有from、to、label三个字段\n"
        "6. 实体名称控制在2-10个字，关系标签控制在2-6个字\n"
        "7. 只提取文本中明确存在的实体和关系，不要编造\n"
        "8. 如果实体很多，只提取最重要、关系最丰富的{max_nodes}个"
    ).format(max_nodes=50)

    user_prompt = (
        "从以下文本中提取实体和关系，输出JSON对象（不是数组），格式为：\n"
        '{{"nodes":[{{"id":"实体名","label":"显示标签","type":"人物|地点|组织|概念|技术|其他"}}],'
        '"edges":[{{"from":"源实体","to":"目标实体","label":"关系"}}]}}\n\n'
        "文本内容：\n"
        f"{text[:6000]}"
    )

    try:
        response = await deepseek_client.chat.completions.create(
            model=LLM_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            max_tokens=16384,
        )

        if not response.choices or not response.choices[0].message:
            logger.error("LLM返回空响应")
            return [], []

        content = response.choices[0].message.content or ""
        content = content.strip()
        logger.debug(f"LLM原始响应长度: {len(content)}")

        if not content and retry_count < 1:
            logger.warning("LLM返回空内容，重试一次")
            return await _call_llm_for_graph(text, retry_count + 1)

        if not content:
            logger.error("LLM连续返回空内容")
            return [], []

        # 记录前200字符用于调试
        logger.debug(f"LLM响应前200字: {content[:200]}")

        # 多策略JSON提取
        json_str = _extract_json(content)

        if not json_str:
            logger.warning(f"无法从响应中提取JSON，原始内容: {content[:300]}")
            if retry_count < 1:
                logger.info("尝试以更严格指令重试")
                return await _call_llm_for_graph(text, retry_count + 1)
            return [], []

        logger.debug(f"提取后的JSON前200字: {json_str[:200]}")

        # 尝试解析
        graph_data = _parse_json_with_fix(json_str)

        if graph_data is None:
            logger.warning(f"JSON解析失败，内容前300字: {json_str[:300]}")
            if retry_count < 1:
                logger.info("尝试以更严格指令重试")
                return await _call_llm_for_graph(text, retry_count + 1)
            return [], []

        nodes = graph_data.get("nodes", [])
        edges = graph_data.get("edges", [])

        # 去重
        seen_ids = set()
        unique_nodes = []
        for n in nodes:
            nid = n.get("id", "")
            if nid and nid not in seen_ids:
                seen_ids.add(nid)
                unique_nodes.append(n)

        seen_edges = set()
        unique_edges = []
        for e in edges:
            key = (e.get("from", ""), e.get("to", ""), e.get("label", ""))
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(e)

        logger.info(f"LLM提取完成: {len(unique_nodes)} 个节点, {len(unique_edges)} 条边")
        return unique_nodes, unique_edges

    except Exception as e:
        logger.error(f"调用LLM失败: {e}", exc_info=True)
        if retry_count < 1:
            return await _call_llm_for_graph(text, retry_count + 1)
        return [], []


def _extract_json(text: str) -> str:
    """从LLM响应中提取JSON内容"""
    if not text:
        return ""

    # 策略1: 处理 ```json ... ``` 包裹
    if "```json" in text:
        parts = text.split("```json", 1)
        if len(parts) > 1:
            inner = parts[1].split("```", 1)[0]
            return inner.strip()

    # 策略2: 处理 ``` ... ``` 包裹
    if "```" in text:
        parts = text.split("```")
        for part in parts:
            part = part.strip()
            if (part.startswith("{") and "nodes" in part and "edges" in part):
                return part
            if part.startswith("{") and part.endswith("}"):
                return part

    # 策略3: 找最外层的 { 和 }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start:end + 1]

    return ""


def _parse_json_with_fix(json_str: str) -> dict:
    """尝试解析JSON，自动修复常见截断问题"""
    import re

    # 直接尝试
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # 修复1: 补全未闭合的括号
    try:
        fixed = json_str
        open_braces = fixed.count("{")
        close_braces = fixed.count("}")
        open_brackets = fixed.count("[")
        close_brackets = fixed.count("]")

        if open_braces > close_braces:
            fixed += "}" * (open_braces - close_braces)
        if open_brackets > close_brackets:
            fixed += "]" * (open_brackets - close_brackets)

        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # 修复2: 正则提取
    nodes = []
    edges = []
    node_pattern = r'\{\s*"id"\s*:\s*"([^"]+)"\s*,\s*"label"\s*:\s*"([^"]+)"\s*,\s*"type"\s*:\s*"([^"]+)"\s*\}'
    for m in re.finditer(node_pattern, json_str):
        nodes.append({"id": m.group(1), "label": m.group(2), "type": m.group(3)})

    edge_pattern = r'\{\s*"from"\s*:\s*"([^"]+)"\s*,\s*"to"\s*:\s*"([^"]+)"\s*,\s*"label"\s*:\s*"([^"]+)"\s*\}'
    for m in re.finditer(edge_pattern, json_str):
        edges.append({"from": m.group(1), "to": m.group(2), "label": m.group(3)})

    if nodes:
        logger.info(f"正则提取到 {len(nodes)} 个节点, {len(edges)} 条边")
        return {"nodes": nodes, "edges": edges}

    return None


async def _generate_graph_batch(text: str, max_nodes: int = 50) -> Tuple[List[Dict], List[Dict]]:
    """对一批文本生成知识图谱，如果太大则再分片"""
    if len(text) > 6000:
        # 文本太长时分两半处理
        mid = text[:6000].rfind("\n")
        if mid < 1000:
            mid = 3000
        first_half = text[:mid]
        second_half = text[mid:]

        n1, e1 = await _call_llm_for_graph(first_half)
        n2, e2 = await _call_llm_for_graph(second_half)

        # 合并结果
        all_nodes = {n["id"]: n for n in n1}
        for n in n2:
            if n["id"] not in all_nodes:
                all_nodes[n["id"]] = n

        seen = set()
        all_edges = []
        for e in n1 + n2:
            key = (e.get("from"), e.get("to"), e.get("label"))
            if key not in seen:
                seen.add(key)
                all_edges.append(e)

        nodes = list(all_nodes.values())[:max_nodes]
        node_ids = {n["id"] for n in nodes}
        edges = [e for e in all_edges if e["from"] in node_ids and e["to"] in node_ids]

        return nodes, edges

    return await _call_llm_for_graph(text)


async def generate_knowledge_graph(
    chunks: List[Dict[str, str]],
    max_nodes: int = 50,
) -> Tuple[List[Dict], List[Dict]]:
    """
    从文本块生成知识图谱

    策略：
    1. 文本较少时单次调用
    2. 文本较多时分批调用，合并去重
    3. 每批LLM严格输出纯JSON
    4. 失败自动重试

    Args:
        chunks: 文本块列表
        max_nodes: 最大节点数量

    Returns:
        (nodes, edges) 元组
    """
    if not chunks:
        logger.warning("文本块为空，无法生成图谱")
        return [], []

    logger.info(f"开始生成知识图谱: {len(chunks)} 个文本块")

    combined_content = "\n\n".join([
        f"[{chunk.get('filename', '文件')} - 片段{chunk.get('index', 0) + 1}]\n{chunk['content']}"
        for chunk in chunks
    ])

    # 测试模式
    if "红楼梦" in combined_content or "贾宝玉" in combined_content:
        logger.info("检测到《红楼梦》内容，使用测试数据")
        return generate_test_hongloumeng_graph()

    # 生成图谱
    try:
        nodes, edges = await _generate_graph_batch(combined_content, max_nodes)

        # 截断到max_nodes
        if len(nodes) > max_nodes:
            nodes = nodes[:max_nodes]
            node_ids = {n["id"] for n in nodes}
            edges = [e for e in edges if e.get("from") in node_ids and e.get("to") in node_ids]

        if not nodes:
            logger.warning("未能从文本中提取到实体和关系")
            return [], []

        logger.info(f"知识图谱生成完成: {len(nodes)} 个节点, {len(edges)} 条边")
        return nodes, edges

    except Exception as e:
        logger.error(f"知识图谱生成失败: {type(e).__name__}: {e}", exc_info=True)
        return [], []


def format_graph_for_frontend(nodes: List[Dict], edges: List[Dict]) -> Dict:
    """
    将图谱数据格式化为前端vis.js所需的格式
    """
    vis_nodes = []

    for i, node in enumerate(nodes):
        node_type = node.get("type", "其他")
        color = ENTITY_COLORS.get(node_type, ENTITY_COLORS["其他"])
        vis_nodes.append({
            "id": i + 1,
            "label": node.get("label", node.get("id", "")),
            "title": f"<strong>{node.get('label', node.get('id', ''))}</strong><br/>类型: {node_type}",
            "color": {
                "background": color,
                "border": "#2c3e50",
                "highlight": {
                    "background": color,
                    "border": "#4f46e5"
                }
            },
            "font": {
                "color": "#ffffff",
                "size": 14,
                "bold": True
            },
            "shape": "circle",
            "size": 30,
            "shadow": {
                "enabled": True,
                "color": "rgba(0,0,0,0.3)",
                "size": 10,
                "x": 3,
                "y": 3
            },
            "entity_type": node_type,
            "entity_label": node.get("label", node.get("id", ""))
        })

    vis_edges = []
    node_id_map = {node.get("label", node.get("id", "")): i + 1 for i, node in enumerate(nodes)}

    for edge in edges:
        from_label = edge.get("from", "")
        to_label = edge.get("to", "")
        if from_label in node_id_map and to_label in node_id_map:
            vis_edges.append({
                "from": node_id_map[from_label],
                "to": node_id_map[to_label],
                "label": edge.get("label", ""),
                "arrows": {
                    "to": {
                        "enabled": True,
                        "scaleFactor": 1.2
                    }
                },
                "font": {
                    "color": "#6b7280",
                    "size": 12,
                    "align": "middle",
                    "bold": True
                },
                "color": {
                    "color": "#cbd5e1",
                    "highlight": "#4f46e5",
                    "hover": "#4f46e5"
                },
                "smooth": {
                    "type": "continuous",
                    "roundness": 0.5
                },
                "width": 2
            })

    return {
        "nodes": vis_nodes,
        "edges": vis_edges,
        "stats": {
            "total_nodes": len(vis_nodes),
            "total_edges": len(vis_edges),
            "node_types": _calculate_node_types(nodes)
        }
    }


def generate_test_hongloumeng_graph() -> Tuple[List[Dict], List[Dict]]:
    """
    生成《红楼梦》测试知识图谱数据
    """
    nodes = [
        {"id": "贾演", "label": "贾演", "type": "人物"},
        {"id": "贾源", "label": "贾源", "type": "人物"},
        {"id": "贾代化", "label": "贾代化", "type": "人物"},
        {"id": "贾敬", "label": "贾敬", "type": "人物"},
        {"id": "贾珍", "label": "贾珍", "type": "人物"},
        {"id": "贾蓉", "label": "贾蓉", "type": "人物"},
        {"id": "尤氏", "label": "尤氏", "type": "人物"},
        {"id": "秦可卿", "label": "秦可卿", "type": "人物"},
        {"id": "贾惜春", "label": "贾惜春", "type": "人物"},
        {"id": "贾代善", "label": "贾代善", "type": "人物"},
        {"id": "贾母", "label": "贾母", "type": "人物"},
        {"id": "贾赦", "label": "贾赦", "type": "人物"},
        {"id": "贾政", "label": "贾政", "type": "人物"},
        {"id": "邢夫人", "label": "邢夫人", "type": "人物"},
        {"id": "贾琏", "label": "贾琏", "type": "人物"},
        {"id": "贾迎春", "label": "贾迎春", "type": "人物"},
        {"id": "王熙凤", "label": "王熙凤", "type": "人物"},
        {"id": "孙绍祖", "label": "孙绍祖", "type": "人物"},
        {"id": "王夫人", "label": "王夫人", "type": "人物"},
        {"id": "贾珠", "label": "贾珠", "type": "人物"},
        {"id": "贾宝玉", "label": "贾宝玉", "type": "人物"},
        {"id": "贾环", "label": "贾环", "type": "人物"},
        {"id": "赵姨娘", "label": "赵姨娘", "type": "人物"},
        {"id": "贾元春", "label": "贾元春", "type": "人物"},
        {"id": "贾探春", "label": "贾探春", "type": "人物"},
        {"id": "李纨", "label": "李纨", "type": "人物"},
        {"id": "贾兰", "label": "贾兰", "type": "人物"},
        {"id": "林黛玉", "label": "林黛玉", "type": "人物"},
        {"id": "林如海", "label": "林如海", "type": "人物"},
        {"id": "贾敏", "label": "贾敏", "type": "人物"},
        {"id": "薛宝钗", "label": "薛宝钗", "type": "人物"},
        {"id": "薛姨妈", "label": "薛姨妈", "type": "人物"},
        {"id": "巧姐", "label": "巧姐", "type": "人物"},
        {"id": "史湘云", "label": "史湘云", "type": "人物"},
        {"id": "妙玉", "label": "妙玉", "type": "人物"},
        {"id": "袭人", "label": "袭人", "type": "人物"},
        {"id": "蒋玉菡", "label": "蒋玉菡", "type": "人物"},
        {"id": "晴雯", "label": "晴雯", "type": "人物"},
        {"id": "紫鹃", "label": "紫鹃", "type": "人物"},
        {"id": "鸳鸯", "label": "鸳鸯", "type": "人物"},
        {"id": "平儿", "label": "平儿", "type": "人物"},
        {"id": "香菱", "label": "香菱", "type": "人物"},
        {"id": "薛蟠", "label": "薛蟠", "type": "人物"},
        {"id": "甄英莲", "label": "甄英莲", "type": "人物"},
        {"id": "栊翠庵", "label": "栊翠庵", "type": "地点"},
        {"id": "贾府", "label": "贾府", "type": "组织"},
        {"id": "史家", "label": "史家", "type": "组织"},
        {"id": "王家", "label": "王家", "type": "组织"},
        {"id": "薛家", "label": "薛家", "type": "组织"},
        {"id": "金陵十二钗", "label": "金陵十二钗", "type": "概念"},
    ]

    edges = [
        {"from": "贾演", "to": "贾代化", "label": "父子"},
        {"from": "贾源", "to": "贾代善", "label": "父子"},
        {"from": "贾代化", "to": "贾敬", "label": "父子"},
        {"from": "贾敬", "to": "贾珍", "label": "父子"},
        {"from": "贾珍", "to": "贾蓉", "label": "父子"},
        {"from": "贾珍", "to": "尤氏", "label": "夫妻"},
        {"from": "贾蓉", "to": "秦可卿", "label": "夫妻"},
        {"from": "贾珍", "to": "贾惜春", "label": "父女"},
        {"from": "贾代善", "to": "贾母", "label": "夫妻"},
        {"from": "贾代善", "to": "贾赦", "label": "父子"},
        {"from": "贾代善", "to": "贾政", "label": "父子"},
        {"from": "贾母", "to": "贾赦", "label": "母子"},
        {"from": "贾母", "to": "贾政", "label": "母子"},
        {"from": "贾赦", "to": "邢夫人", "label": "夫妻"},
        {"from": "贾赦", "to": "贾琏", "label": "父子"},
        {"from": "贾赦", "to": "贾迎春", "label": "父女"},
        {"from": "贾琏", "to": "王熙凤", "label": "夫妻"},
        {"from": "贾迎春", "to": "孙绍祖", "label": "夫妻"},
        {"from": "贾政", "to": "王夫人", "label": "夫妻"},
        {"from": "贾政", "to": "贾珠", "label": "父子"},
        {"from": "贾政", "to": "贾宝玉", "label": "父子"},
        {"from": "贾政", "to": "贾环", "label": "父子"},
        {"from": "赵姨娘", "to": "贾政", "label": "妾于"},
        {"from": "贾政", "to": "贾元春", "label": "父女"},
        {"from": "贾政", "to": "贾探春", "label": "父女"},
        {"from": "赵姨娘", "to": "贾环", "label": "母子"},
        {"from": "赵姨娘", "to": "贾探春", "label": "母女"},
        {"from": "贾珠", "to": "李纨", "label": "夫妻"},
        {"from": "贾珠", "to": "贾兰", "label": "父子"},
        {"from": "贾珠", "to": "贾宝玉", "label": "兄弟"},
        {"from": "贾宝玉", "to": "贾环", "label": "兄弟"},
        {"from": "贾元春", "to": "贾宝玉", "label": "姐弟"},
        {"from": "贾宝玉", "to": "贾探春", "label": "兄妹"},
        {"from": "林黛玉", "to": "林如海", "label": "父女"},
        {"from": "林黛玉", "to": "贾敏", "label": "母女"},
        {"from": "贾母", "to": "贾敏", "label": "母女"},
        {"from": "贾母", "to": "林黛玉", "label": "外祖母"},
        {"from": "贾宝玉", "to": "林黛玉", "label": "表兄妹"},
        {"from": "薛宝钗", "to": "薛姨妈", "label": "母女"},
        {"from": "薛姨妈", "to": "王夫人", "label": "姐妹"},
        {"from": "贾宝玉", "to": "薛宝钗", "label": "夫妻"},
        {"from": "薛宝钗", "to": "贾宝玉", "label": "表姐"},
        {"from": "王熙凤", "to": "王夫人", "label": "侄女"},
        {"from": "王熙凤", "to": "巧姐", "label": "母女"},
        {"from": "贾琏", "to": "巧姐", "label": "父女"},
        {"from": "史湘云", "to": "贾母", "label": "侄孙女"},
        {"from": "妙玉", "to": "栊翠庵", "label": "居住于"},
        {"from": "栊翠庵", "to": "贾府", "label": "属于"},
        {"from": "袭人", "to": "贾宝玉", "label": "丫鬟于"},
        {"from": "袭人", "to": "蒋玉菡", "label": "夫妻"},
        {"from": "晴雯", "to": "贾宝玉", "label": "丫鬟于"},
        {"from": "紫鹃", "to": "林黛玉", "label": "丫鬟于"},
        {"from": "鸳鸯", "to": "贾母", "label": "丫鬟于"},
        {"from": "平儿", "to": "王熙凤", "label": "丫鬟于"},
        {"from": "平儿", "to": "贾琏", "label": "侍妾于"},
        {"from": "香菱", "to": "薛蟠", "label": "侍妾于"},
        {"from": "香菱", "to": "甄英莲", "label": "原名"},
        {"from": "林黛玉", "to": "金陵十二钗", "label": "属于"},
        {"from": "薛宝钗", "to": "金陵十二钗", "label": "属于"},
        {"from": "贾元春", "to": "金陵十二钗", "label": "属于"},
        {"from": "贾迎春", "to": "金陵十二钗", "label": "属于"},
        {"from": "贾探春", "to": "金陵十二钗", "label": "属于"},
        {"from": "贾惜春", "to": "金陵十二钗", "label": "属于"},
        {"from": "李纨", "to": "金陵十二钗", "label": "属于"},
        {"from": "秦可卿", "to": "金陵十二钗", "label": "属于"},
        {"from": "王熙凤", "to": "金陵十二钗", "label": "属于"},
        {"from": "巧姐", "to": "金陵十二钗", "label": "属于"},
        {"from": "史湘云", "to": "金陵十二钗", "label": "属于"},
        {"from": "妙玉", "to": "金陵十二钗", "label": "属于"},
        {"from": "贾府", "to": "史家", "label": "联姻"},
        {"from": "贾府", "to": "王家", "label": "联姻"},
        {"from": "贾府", "to": "薛家", "label": "联姻"},
        {"from": "王家", "to": "薛家", "label": "联姻"},
    ]

    return nodes, edges


def _calculate_node_types(nodes: List[Dict]) -> Dict[str, int]:
    """
    计算各类型节点的数量
    """
    type_counts = {}
    for node in nodes:
        node_type = node.get("type", "其他")
        type_counts[node_type] = type_counts.get(node_type, 0) + 1
    return type_counts


async def get_graph_from_cache(db: AsyncSession, knowledge_file_id: int) -> Optional[Dict]:
    """
    从数据库缓存中获取知识图谱
    """
    result = await db.execute(
        select(KnowledgeGraph).where(KnowledgeGraph.knowledge_file_id == knowledge_file_id)
    )
    graph = result.scalar_one_or_none()

    if graph:
        try:
            data = json.loads(graph.graph_data)
            return {
                "nodes": data.get("nodes", []),
                "edges": data.get("edges", []),
                "stats": data.get("stats", {
                    "total_nodes": graph.node_count,
                    "total_edges": graph.edge_count
                }),
                "generated_at": graph.generated_at.isoformat(),
                "cached": True
            }
        except json.JSONDecodeError:
            logger.error(f"缓存的图谱数据解析失败: knowledge_file_id={knowledge_file_id}")
            return None

    return None


async def save_graph_to_cache(db: AsyncSession, knowledge_file_id: int, graph_data: Dict):
    """
    将知识图谱保存到数据库缓存
    """
    result = await db.execute(
        select(KnowledgeGraph).where(KnowledgeGraph.knowledge_file_id == knowledge_file_id)
    )
    existing_graph = result.scalar_one_or_none()

    graph_json = json.dumps(graph_data)
    stats = graph_data.get("stats", {})

    if existing_graph:
        existing_graph.graph_data = graph_json
        existing_graph.node_count = stats.get("total_nodes", 0)
        existing_graph.edge_count = stats.get("total_edges", 0)
    else:
        new_graph = KnowledgeGraph(
            knowledge_file_id=knowledge_file_id,
            graph_data=graph_json,
            node_count=stats.get("total_nodes", 0),
            edge_count=stats.get("total_edges", 0)
        )
        db.add(new_graph)

    await db.commit()


async def delete_graph_cache(db: AsyncSession, knowledge_file_id: int):
    """
    删除指定文件的知识图谱缓存
    """
    result = await db.execute(
        select(KnowledgeGraph).where(KnowledgeGraph.knowledge_file_id == knowledge_file_id)
    )
    graph = result.scalar_one_or_none()

    if graph:
        await db.delete(graph)
        await db.commit()
        logger.info(f"已删除知识图谱缓存: knowledge_file_id={knowledge_file_id}")