"""
今日课表服务模块：实现教务系统登录和课表数据获取

功能流程：
1. 日期获取：通过datetime模块获取当前系统日期
2. 教务系统登录：访问教务系统登录页面，处理验证码，进行身份验证
3. 课表数据获取：调用API获取当日课程信息
4. 数据处理：格式化处理原始数据，提取关键信息

注意：由于实际教务系统访问限制，本模块包含模拟数据作为备用方案
"""
import logging
import os
import re
import httpx
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

# OCR相关导入
try:
    import ddddocr
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False
    logger = logging.getLogger("course_schedule")
    logger.warning("ddddocr库未安装，验证码识别功能将使用模拟模式")

logger = logging.getLogger("course_schedule")

# 教务系统配置
CONFIG = {
    "base_url": "http://xk.csust.edu.cn/",
    "login_url": "http://xk.csust.edu.cn/Logon.do?method=logon",
    "api_url": "http://xk.csust.edu.cn/jsxsd/xskb/xskb_list.do",
    "account": "202202140215",
    "password": "123@Kongchen",
    "captcha_url": "http://xk.csust.edu.cn/verifycode.servlet",
}

# 模拟课表数据（用于测试和演示）
MOCK_SCHEDULE_DATA = {
    "2024-02-19": [
        {"课程名称": "高等数学", "上课时间": "08:00-09:40", "地点": "教学楼A-301", "教师": "张教授", "节次": "1-2"},
        {"课程名称": "大学英语", "上课时间": "10:00-11:40", "地点": "教学楼B-205", "教师": "李老师", "节次": "3-4"},
        {"课程名称": "数据结构", "上课时间": "14:00-15:40", "地点": "实验楼C-102", "教师": "王教授", "节次": "5-6"},
    ],
    "2024-02-20": [
        {"课程名称": "计算机网络", "上课时间": "08:00-09:40", "地点": "教学楼A-403", "教师": "刘老师", "节次": "1-2"},
        {"课程名称": "操作系统", "上课时间": "14:00-15:40", "地点": "实验楼C-201", "教师": "陈教授", "节次": "5-6"},
        {"课程名称": "软件工程", "上课时间": "16:00-17:40", "地点": "教学楼B-302", "教师": "赵老师", "节次": "7-8"},
    ],
    "2024-02-21": [
        {"课程名称": "高等数学", "上课时间": "10:00-11:40", "地点": "教学楼A-301", "教师": "张教授", "节次": "3-4"},
        {"课程名称": "大学物理", "上课时间": "14:00-15:40", "地点": "物理楼D-101", "教师": "周教授", "节次": "5-6"},
    ],
    "2024-02-22": [
        {"课程名称": "数据结构", "上课时间": "08:00-09:40", "地点": "实验楼C-102", "教师": "王教授", "节次": "1-2"},
        {"课程名称": "计算机网络", "上课时间": "14:00-15:40", "地点": "教学楼A-403", "教师": "刘老师", "节次": "5-6"},
    ],
    "2024-02-23": [
        {"课程名称": "大学英语", "上课时间": "08:00-09:40", "地点": "教学楼B-205", "教师": "李老师", "节次": "1-2"},
        {"课程名称": "操作系统", "上课时间": "10:00-11:40", "地点": "实验楼C-201", "教师": "陈教授", "节次": "3-4"},
        {"课程名称": "概率论", "上课时间": "14:00-15:40", "地点": "教学楼A-201", "教师": "吴教授", "节次": "5-6"},
    ],
}


def get_current_date_str() -> str:
    """
    获取当前系统日期，格式为YYYY-MM-DD，符合教务系统日期标准

    Returns:
        当前日期字符串，格式：YYYY-MM-DD
    """
    today = date.today()
    return today.strftime("%Y-%m-%d")


def get_weekday_name(date_str: str) -> str:
    """
    获取日期对应的星期名称

    Args:
        date_str: 日期字符串，格式YYYY-MM-DD

    Returns:
        星期名称（如：星期一）
    """
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        return weekdays[dt.weekday()]
    except ValueError:
        return ""


async def download_captcha(session: httpx.AsyncClient, captcha_url: str) -> Optional[bytes]:
    """
    下载验证码图片

    Args:
        session: HTTP会话
        captcha_url: 验证码图片URL

    Returns:
        验证码图片字节数据，如果失败返回None
    """
    try:
        response = await session.get(captcha_url)
        response.raise_for_status()
        if response.headers.get("content-type", "").startswith("image/"):
            return response.content
        logger.error(f"验证码下载失败：返回内容不是图片类型")
        return None
    except Exception as e:
        logger.error(f"下载验证码图片失败: {e}", exc_info=True)
        return None


async def recognize_captcha(captcha_image: bytes) -> str:
    """
    使用ddddocr深度学习模型识别验证码

    ddddocr是专门针对验证码场景训练的深度学习OCR模型，
    无需额外预处理，直接传入图片bytes即可识别。

    Args:
        captcha_image: 验证码图片字节数据

    Returns:
        识别出的验证码字符串
    """
    if not OCR_AVAILABLE:
        logger.warning("ddddocr库不可用，使用模拟验证码")
        return "ABCD"

    try:
        ocr = ddddocr.DdddOcr(show_ad=False)
        result = ocr.classification(captcha_image)
        
        captcha_code = result.strip() if result else ""
        
        if len(captcha_code) < 4:
            logger.warning(f"ddddocr识别结果太短: '{captcha_code}'，使用模拟验证码")
            return "ABCD"
        
        logger.info(f"ddddocr识别成功: {captcha_code}")
        return captcha_code
    
    except Exception as e:
        logger.error(f"ddddocr识别失败: {e}", exc_info=True)
        return "ABCD"


def _encode_credentials(username: str, password: str, scode: str, sxh: str) -> str:
    """
    模拟前端JS的密码加密算法

    前端JS逻辑：
    1. code = username + "%%%" + password
    2. 循环前20个字符，将code[i]与scode的前sxh[i]个字符交错拼接
    3. 剩余code字符直接追加

    Args:
        username: 用户名
        password: 密码
        scode: 服务端返回的随机密钥
        sxh: 服务端返回的位置映射字符串（每位数字表示取scode的前几个字符）

    Returns:
        加密后的凭证字符串
    """
    code = username + "%%%" + password
    encoded = ""
    
    for i in range(min(len(code), 20)):
        n = int(sxh[i])
        encoded += code[i] + scode[:n]
        scode = scode[n:]
    
    if len(code) > 20:
        encoded += code[20:]
    
    return encoded


async def login_jw_system(username: str = None, password: str = None) -> dict:
    """
    登录教务系统（含验证码OCR识别和前端密码加密模拟）

    登录流程：
    1. 获取登录页面，建立Session
    2. 下载验证码图片并OCR识别
    3. 调用flag=sess接口获取加密密钥
    4. 使用密钥加密用户名密码
    5. 提交加密后的登录表单

    Args:
        username: 教务系统用户名（可选，不传则使用配置中的默认值）
        password: 教务系统密码（可选，不传则使用配置中的默认值）

    Returns:
        登录结果字典，包含：
        - success: 是否成功
        - session: 已登录的HTTP会话对象（成功时）
        - error_type: 错误类型（失败时），如 "password_error", "captcha_error", "network_error" 等
        - error_message: 错误消息
    """
    # 使用传入的账号密码或默认配置
    account = username or CONFIG["account"]
    pwd = password or CONFIG["password"]
    
    logger.info(f"开始登录教务系统: {CONFIG['base_url']}, account={account}")

    session = httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )

    try:
        # 1. 获取登录页面
        logger.info("获取登录页面...")
        response = await session.get(CONFIG["base_url"])
        response.raise_for_status()
        logger.info(f"登录页面获取成功")

        # 2. 获取验证码
        logger.info("获取验证码图片...")
        captcha_image = await download_captcha(session, CONFIG["captcha_url"])
        if not captcha_image:
            await session.aclose()
            return {
                "success": False,
                "error_type": "captcha_error",
                "error_message": "无法获取验证码图片"
            }
        logger.info("验证码图片获取成功")

        # 3. OCR识别验证码
        captcha_code = await recognize_captcha(captcha_image)
        logger.info(f"OCR识别验证码: {captcha_code}")

        # 4. 获取加密密钥（模拟前端AJAX调用）
        logger.info("获取加密密钥...")
        sess_url = "http://xk.csust.edu.cn/Logon.do?method=logon&flag=sess"
        sess_resp = await session.post(sess_url)
        sess_data = sess_resp.text.strip()
        logger.info(f"密钥响应: {sess_data}")

        if not sess_data or sess_data == "no":
            await session.aclose()
            return {
                "success": False,
                "error_type": "system_error",
                "error_message": "获取加密密钥失败"
            }

        # 解析密钥：scode#sxh
        parts = sess_data.split("#")
        if len(parts) < 2:
            await session.aclose()
            return {
                "success": False,
                "error_type": "system_error",
                "error_message": f"密钥格式异常: {sess_data}"
            }
        scode, sxh = parts[0], parts[1]
        logger.info(f"密钥解析成功: scode长度={len(scode)}, sxh={sxh}")

        # 5. 加密用户名密码
        encoded = _encode_credentials(account, pwd, scode, sxh)
        logger.info(f"凭证加密完成, encoded长度={len(encoded)}")

        # 6. 构造登录表单（模拟前端提交）
        login_data = {
            "userAccount": "",
            "userPassword": "",
            "RANDOMCODE": captcha_code,
            "encoded": encoded,
        }

        # 7. 提交登录表单（禁用自动重定向以便检查响应）
        session_no_redirect = httpx.AsyncClient(
            timeout=30,
            follow_redirects=False,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
            cookies=session.cookies
        )
        
        logger.info("提交加密登录表单...")
        response = await session_no_redirect.post(CONFIG["login_url"], data=login_data)
        logger.info(f"登录响应状态码: {response.status_code}")

        # 8. 判断登录是否成功
        if response.status_code == 302:
            # 重定向表示登录成功
            redirect_url = response.headers.get("Location", "")
            logger.info(f"登录成功，重定向到: {redirect_url}")
            
            # 合并cookies
            for cookie in response.cookies.jar:
                session.cookies.set(cookie.name, cookie.value)
            
            await session_no_redirect.aclose()
            return {
                "success": True,
                "session": session,
                "error_type": None,
                "error_message": None
            }
        elif response.status_code == 200:
            text = response.text
            
            # 检查错误信息
            if "验证码错误" in text:
                await session.aclose()
                await session_no_redirect.aclose()
                return {
                    "success": False,
                    "error_type": "captcha_error",
                    "error_message": "验证码错误"
                }
            elif "用户名或密码" in text or "账号或密码" in text:
                await session.aclose()
                await session_no_redirect.aclose()
                return {
                    "success": False,
                    "error_type": "password_error",
                    "error_message": "用户名或密码错误"
                }
            elif "计算异常" in text:
                await session.aclose()
                await session_no_redirect.aclose()
                return {
                    "success": False,
                    "error_type": "system_error",
                    "error_message": "加密计算异常"
                }
            else:
                await session.aclose()
                await session_no_redirect.aclose()
                return {
                    "success": False,
                    "error_type": "unknown_error",
                    "error_message": f"登录失败，响应URL: {response.url}"
                }
        else:
            await session.aclose()
            await session_no_redirect.aclose()
            return {
                "success": False,
                "error_type": "http_error",
                "error_message": f"登录失败，HTTP状态码: {response.status_code}"
            }

    except httpx.ConnectError:
        await session.aclose()
        return {
            "success": False,
            "error_type": "network_error",
            "error_message": "网络连接异常，无法访问教务系统"
        }
    except httpx.TimeoutException:
        await session.aclose()
        return {
            "success": False,
            "error_type": "timeout_error",
            "error_message": "连接教务系统超时"
        }
    except Exception as e:
        await session.aclose()
        logger.error(f"登录教务系统发生错误: {e}", exc_info=True)
        return {
            "success": False,
            "error_type": "system_error",
            "error_message": str(e)
        }


async def get_class_info(session: httpx.AsyncClient, target_date: str) -> List[Dict[str, Any]]:
    """
    获取指定日期的课程信息（解析HTML课表页面）

    Args:
        session: 已登录的HTTP会话
        target_date: 目标日期，格式YYYY-MM-DD

    Returns:
        课程信息列表
    """
    logger.info(f"获取 {target_date} 的课程信息")

    try:
        response = await session.get(CONFIG["api_url"])
        response.raise_for_status()
        html = response.text

        # 解析课表表格
        courses = _parse_kb_table(html, target_date)
        return courses

    except httpx.HTTPStatusError as e:
        logger.error(f"获取课表数据HTTP错误: {e.response.status_code}")
        return []
    except Exception as e:
        logger.error(f"获取课表数据发生错误: {e}", exc_info=True)
        return []


def _parse_kb_table(html: str, target_date: str) -> List[Dict[str, Any]]:
    """
    解析课表HTML表格，提取指定日期的课程

    Args:
        html: 课表页面HTML
        target_date: 目标日期 YYYY-MM-DD

    Returns:
        课程信息列表
    """
    # 计算目标日期是星期几，映射到表格列索引
    # 表格列顺序：0=星期日, 1=星期一, ..., 6=星期六
    dt = datetime.strptime(target_date, "%Y-%m-%d")
    weekday_python = dt.weekday()  # 0=Monday, 6=Sunday
    # 映射：Python weekday -> table column
    # Monday(0)->1, Tuesday(1)->2, ..., Saturday(5)->6, Sunday(6)->0
    if weekday_python == 6:
        col_index = 0  # 星期日
    else:
        col_index = weekday_python + 1  # 星期一=1, ...
    
    # 解析表格行
    # 匹配每个 tr（跳过表头行）
    tr_pattern = re.compile(r'<tr>(.*?)</tr>', re.DOTALL)
    td_pattern = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL)
    
    trs = tr_pattern.findall(html)
    
    courses = []
    
    for tr_html in trs:
        tds = td_pattern.findall(tr_html)
        if len(tds) < 8:
            continue
        
        # 第一列是时间槽
        time_slot_html = tds[0]
        time_match = re.search(r'(\d{2}:\d{2})-(\d{2}:\d{2})', time_slot_html)
        if not time_match:
            continue
        
        start_time = time_match.group(1)
        end_time = time_match.group(2)
        time_str = f"{start_time}-{end_time}"
        
        # 获取目标列的课程内容
        if col_index >= len(tds):
            continue
        
        cell_html = tds[col_index]
        
        # 提取kbcontent div中的内容
        kb_divs = re.findall(r'<div[^>]*class=["\']?kbcontent[^"\']*["\']?[^>]*>(.*?)</div>', cell_html, re.DOTALL)
        
        for div_content in kb_divs:
            div_content = div_content.strip()
            if not div_content or div_content == "&nbsp;":
                continue
            
            # 解析课程信息
            # 格式通常为：课程名称\n教师\n教室\n周次
            lines = [line.strip() for line in div_content.split("<br>") if line.strip()]
            # 也尝试用 <br/> 分割
            if len(lines) <= 1:
                lines = [line.strip() for line in div_content.split("<br/>") if line.strip()]
            # 清理HTML标签
            clean_lines = [re.sub(r'<[^>]+>', '', line).strip() for line in lines]
            # 过滤空行
            clean_lines = [l for l in clean_lines if l]
            
            if not clean_lines:
                continue
            
            course_info = {
                "课程名称": clean_lines[0] if len(clean_lines) > 0 else "未知课程",
                "上课时间": time_str,
                "教师": "",
                "地点": "",
                "节次": "",
            }
            
            # 尝试从剩余行解析教师和地点
            for line in clean_lines[1:]:
                if "教师" in line or "老师" in line or "教授" in line:
                    course_info["教师"] = line
                elif re.match(r'^[\u4e00-\u9fa5]{2,4}$', line) and not course_info["教师"]:
                    # 可能是一个人名（2-4个中文字符）
                    course_info["教师"] = line
                elif "楼" in line or "教" in line or "室" in line or "栋" in line:
                    course_info["地点"] = line
                elif re.match(r'^[\u4e00-\u9fa5\d]+楼', line):
                    course_info["地点"] = line
                else:
                    # 如果还没分配，尝试分配
                    if not course_info["教师"] and len(line) <= 6:
                        course_info["教师"] = line
                    elif not course_info["地点"]:
                        course_info["地点"] = line
            
            courses.append(course_info)
    
    logger.info(f"解析到 {len(courses)} 门课程")
    return courses


def format_schedule_data(raw_data: List[Dict[str, Any]]) -> str:
    """
    格式化课表数据为自然语言格式

    Args:
        raw_data: 原始课表数据列表

    Returns:
        格式化后的自然语言字符串
    """
    if not raw_data:
        return "今日暂无课程安排"

    # 按节次排序
    sorted_data = sorted(raw_data, key=lambda x: int(x.get("节次", "1").split("-")[0]) if x.get("节次") else 1)

    result = []
    for idx, course in enumerate(sorted_data, 1):
        course_name = course.get("课程名称", "未知课程")
        class_time = course.get("上课时间", "时间未知")
        location = course.get("地点", "地点未知")
        teacher = course.get("教师", "教师未知")
        section = course.get("节次", "")

        line = f"{idx}. {course_name}"
        if class_time:
            line += f" ({class_time})"
        if location:
            line += f"，地点：{location}"
        if teacher:
            line += f"，教师：{teacher}"

        result.append(line)

    return "\n".join(result)


async def get_today_schedule(use_mock: bool = False, username: str = None, password: str = None) -> Dict[str, Any]:
    """
    获取今日课表信息（主入口函数）

    Args:
        use_mock: 是否使用模拟数据（默认False，使用真实教务系统）
        username: 教务系统用户名（可选，不传则使用配置中的默认值）
        password: 教务系统密码（可选，不传则使用配置中的默认值）

    Returns:
        包含课表信息的字典，格式：
        {
            "success": bool,
            "date": str,
            "weekday": str,
            "schedule": str,
            "error_type": str (可选)，如 "password_error", "captcha_error" 等
            "error": str (可选)
        }
    """
    today = get_current_date_str()
    weekday = get_weekday_name(today)

    logger.info(f"获取今日课表: {today} ({weekday}), use_mock={use_mock}, username={username or 'default'}")

    # 如果使用模拟数据
    if use_mock:
        logger.info("使用模拟课表数据")
        # 获取今天或最近的工作日数据作为演示
        mock_data = MOCK_SCHEDULE_DATA.get(today, [])

        # 如果今天没有数据，找一个最近的有数据的日期
        if not mock_data:
            for date_key in sorted(MOCK_SCHEDULE_DATA.keys()):
                mock_data = MOCK_SCHEDULE_DATA[date_key]
                break

        schedule_text = format_schedule_data(mock_data)

        return {
            "success": True,
            "date": today,
            "weekday": weekday,
            "schedule": schedule_text,
            "message": f"📅 {today} ({weekday}) 课表\n\n{schedule_text}"
        }

    # 实际调用教务系统
    session = None
    try:
        # 1. 登录教务系统
        login_result = await login_jw_system(username=username, password=password)
        
        if not login_result["success"]:
            error_type = login_result.get("error_type", "unknown_error")
            error_message = login_result.get("error_message", "登录失败")
            
            # 密码错误时给出明确提示
            if error_type == "password_error":
                return {
                    "success": False,
                    "date": today,
                    "weekday": weekday,
                    "error_type": "password_error",
                    "error": "密码错误，请检查您的教务系统账号密码",
                    "message": "密码错误，请检查您的教务系统账号密码后重试"
                }
            
            return {
                "success": False,
                "date": today,
                "weekday": weekday,
                "error_type": error_type,
                "error": error_message,
                "message": f"抱歉，暂时无法获取课表信息：{error_message}"
            }

        session = login_result["session"]

        # 2. 获取课表数据
        raw_data = await get_class_info(session, today)

        # 3. 格式化数据
        schedule_text = format_schedule_data(raw_data)

        return {
            "success": True,
            "date": today,
            "weekday": weekday,
            "schedule": schedule_text,
            "message": f"📅 {today} ({weekday}) 课表\n\n{schedule_text}"
        }

    except Exception as e:
        logger.error(f"获取今日课表失败: {e}", exc_info=True)
        return {
            "success": False,
            "date": today,
            "weekday": weekday,
            "error_type": "system_error",
            "error": str(e),
            "message": "抱歉，获取课表信息时发生错误，请稍后重试"
        }
    finally:
        # 确保session被正确关闭
        if session:
            await session.aclose()


async def get_schedule_by_date(target_date: str) -> Dict[str, Any]:
    """
    获取指定日期的课表信息

    Args:
        target_date: 目标日期，格式YYYY-MM-DD

    Returns:
        包含课表信息的字典
    """
    # 验证日期格式
    try:
        datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError:
        return {
            "success": False,
            "error": "日期格式错误，请使用YYYY-MM-DD格式",
            "message": "日期格式错误，请使用YYYY-MM-DD格式"
        }

    weekday = get_weekday_name(target_date)
    logger.info(f"获取指定日期课表: {target_date} ({weekday})")

    # 使用模拟数据
    mock_data = MOCK_SCHEDULE_DATA.get(target_date, [])
    schedule_text = format_schedule_data(mock_data)

    return {
        "success": True,
        "date": target_date,
        "weekday": weekday,
        "schedule": schedule_text,
        "message": f"📅 {target_date} ({weekday}) 课表\n\n{schedule_text}"
    }