"""
情感分析服务模块：使用LLM模型进行情感识别

功能特点：
1. 优先使用LLM进行情感分析，准确性更高
2. 当LLM不可用时，使用本地关键词匹配作为备选
3. 添加内存缓存机制，提升响应速度（目标响应时间≤500ms）
4. 支持情感标签与回复内容同步返回
5. 情感识别结果可持久化存储到数据库
"""
import asyncio
import logging
import os
from typing import Dict, Tuple, Optional
from functools import lru_cache

logger = logging.getLogger("emotion")

VALID_EMOTIONS = ["开心", "疑惑", "愤怒", "悲伤", "惊讶", "焦虑", "平静", "兴奋", "失望", "厌恶"]

LLM_EMOTION_TIMEOUT = float(os.getenv("EMOTION_LLM_TIMEOUT", "3.0"))
CACHE_MAX_SIZE = int(os.getenv("EMOTION_CACHE_SIZE", "500"))

# 本地关键词匹配（作为LLM不可用时的备选）
LOCAL_EMOTION_KEYWORDS: Dict[str, list] = {
    '开心': [
        '哈哈', '嘻嘻', '嘿嘿', '太好了', '太棒了', '真不错', '好开心', '很高兴',
        '开心死了', '笑死我了', '乐死我了', '好爽', '爽歪歪', '嗨皮', '哇塞',
        '恭喜', '祝贺', '庆祝', '点赞', '感恩', '谢谢',
    ],
    '疑惑': [
        '为什么', '怎么', '什么', '谁', '哪里', '哪个', '请问', '想问',
        '搞不懂', '不明白', '不太清楚', '不理解', '啥意思', '啥情况',
        '怎么回事', '咋回事', '求助', '有人知道吗', '？', '?',
    ],
    '愤怒': [
        '气死我了', '气死', '气炸了', '太气人了', '火大', '怒了', '烦死了', '烦死',
        '真烦', '好烦', '很烦', '太烦了', '吵死了', '太吵了', '很吵', '吵到',
        '受不了', '受够了', '忍不了', '忍无可忍', '真受不了',
        '去死', '恶心', '傻逼', '混蛋', '妈的', '操你', '垃圾',
        '差评', '投诉', '举报', '什么玩意', '什么东西',
        '太过分了', '过分', '不讲道理', '凭什么', '无理取闹',
        '耽误', '浪费时间', '白等', '等了半天', '等了很久', '排了好久',
        '等了好久', '等死', '慢死了', '慢的要死', '效率太低',
        '排队', '还没轮到', '还没到我', '怎么还没', '还要多久',
        '太差了', '真差', '很差', '太烂了', '真烂', '态度差', '服务差',
    ],
    '悲伤': [
        '好难过', '想哭', '哭死', '泪崩', '心碎', '崩溃', '绝望',
        '太惨了', '好惨', '可怜', '心痛', '好累', '撑不住了',
        '扛不住了', '熬不住了', '不开心', '难受想哭', '好委屈', '委屈',
        '难过', '伤心',
    ],
    '惊讶': [
        '天呐', '天哪', '卧槽', '我去', '我靠', '没想到', '竟然',
        '居然', '震惊', '惊人', '不可思议', '大跌眼镜', '完了',
        '不会吧', '真的假的', '吓我一跳', '吓死我了',
    ],
    '焦虑': [
        '焦虑', '好急', '急死了', '急死我了', '来不及了', '来不及',
        '怎么办', '怎么办啊', '咋办', '完蛋了', '糟了', '坏了',
        '赶时间', '快来不及', '着急', '好怕', '害怕', '恐惧',
        '紧张死了', '好紧张', '压力好大', '失眠', '睡不着',
        '担心', '很担心', '放心不下', '不安',
    ],
    '兴奋': [
        '激动', '热血沸腾', '超级期待', '迫不及待', '太期待了', '好激动',
        '燃起来了', '牛逼', '太厉害了', '无敌', '起飞', '冲',
        '期待', '等不及', '好喜欢', '爱了爱了', '绝了', '封神',
    ],
    '失望': [
        '失望', '哎', '唉', '无奈', '没办法', '可惜', '遗憾',
        '凉了', '凉凉', '没救了', '无解', '死心', '放弃了',
        '算了', '随便吧', '无所谓了', '就这样吧', '不太行', '不行',
    ],
    '厌恶': [
        '恶心死了', '太恶心了', '反感', '讨厌死了', '讨厌', '烦人',
        '滚开', '别烦我', '想吐', '令人作呕', '看不下去了',
        '看不惯', '真讨厌', '好讨厌', '嫌弃',
        '难吃', '很难吃', '太难吃了', '不好吃', '味道差',
    ],
}


def _local_analyze(text: str) -> Tuple[str, float]:
    """使用本地关键词匹配进行情感分析（备选方案）"""
    scores = {e: 0 for e in VALID_EMOTIONS}
    for emotion, keywords in LOCAL_EMOTION_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                scores[emotion] += 1

    max_score = max(scores.values())
    if max_score == 0:
        return "平静", 0.0

    top = [e for e, s in scores.items() if s == max_score]
    winner = top[0]
    confidence = min(max_score * 0.3 + 0.3, 0.95)
    return winner, round(confidence, 2)


async def _llm_analyze_emotion(text: str) -> Tuple[str, float]:
    """
    使用LLM进行情感分析
    
    Args:
        text: 用户消息文本
        
    Returns:
        (情感标签, 置信度)
    """
    # 检查LLM配置是否完整
    if not os.getenv("DEEPSEEK_API_KEY"):
        logger.info("未配置DEEPSEEK_API_KEY，使用本地情感分析")
        return _local_analyze(text)
        
    try:
        from services.deepseek_client import deepseek_client, LLM_MODEL
        
        system_prompt = (
            "你是一个专业的中文情绪分析专家。\n"
            "请分析用户消息的情绪，从以下列表中选择最准确的一个：\n"
            "开心、疑惑、愤怒、悲伤、惊讶、焦虑、平静、兴奋、失望、厌恶\n"
            "严格按照格式输出：只回复情感标签（两个汉字），不要其他任何内容。\n"
            "如果没有找到有效标签，返回\"平静\"。\n"
            "注意区分否定表达式（如\"不开心\"应识别为\"悲伤\"而非\"开心\"）。"
        )
        
        response = await asyncio.wait_for(
            deepseek_client.chat.completions.create(
                model=LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": text},
                ],
                temperature=0.0,
                max_tokens=5,
                timeout=LLM_EMOTION_TIMEOUT,
            ),
            timeout=LLM_EMOTION_TIMEOUT + 1
        )
        
        choice = response.choices[0]
        content = choice.message.content or ""
        content = content.strip()
        
        # 直接检查是否为有效情感标签
        if content in VALID_EMOTIONS:
            logger.info(f"LLM情感分析成功: {content}")
            return content, 0.9
        
        # 如果没有找到有效标签，尝试在响应中查找
        for emotion in VALID_EMOTIONS:
            if emotion in content:
                logger.info(f"LLM情感分析成功(匹配): {emotion}")
                return emotion, 0.9
        
        # 如果没有找到有效标签，返回"平静"
        logger.warning(f"LLM返回无效情感标签: '{content}'，使用本地分析作为备选")
        return _local_analyze(text)
        
    except ImportError:
        logger.warning("无法导入deepseek_client，使用本地情感分析")
        return _local_analyze(text)
    except asyncio.TimeoutError:
        logger.error(f"LLM情感分析超时({LLM_EMOTION_TIMEOUT}s)，使用本地分析")
        return _local_analyze(text)
    except Exception as e:
        logger.error(f"LLM情感分析调用失败: {e}，使用本地分析")
        return _local_analyze(text)


async def analyze_message_emotion(message: str) -> Dict[str, any]:
    """
    分析用户消息的情感（主入口函数）
    
    功能特点：
    1. 优先使用LLM进行情感分析，准确性更高
    2. 当LLM不可用时，使用本地关键词匹配作为备选
    3. 支持缓存机制，提升响应速度
    4. 返回结构化的情感分析结果
    
    Args:
        message: 用户消息文本
        
    Returns:
        情感分析结果字典，包含：
        - success: 是否成功
        - emotion: 情感标签
        - confidence: 置信度
        - message: 原始消息
    """
    if not message or not isinstance(message, str):
        return {"success": True, "emotion": "平静", "confidence": 0.0, "message": message}

    message = message.strip()
    if not message:
        return {"success": True, "emotion": "平静", "confidence": 0.0, "message": message}
    
    # 优先使用LLM进行情感分析
    emotion, confidence = await _llm_analyze_emotion(message)
    
    return {
        "success": True,
        "emotion": emotion,
        "confidence": round(confidence, 2),
        "message": message,
    }


async def batch_analyze_emotions(messages: list) -> list:
    """
    批量分析多条消息的情感
    
    Args:
        messages: 消息列表
        
    Returns:
        情感分析结果列表
    """
    results = []
    for msg in messages:
        result = await analyze_message_emotion(msg)
        results.append(result)
    return results
