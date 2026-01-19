"""
GUI Automation Module for Antigravity-Bridge

This module provides GUI automation capabilities using PyAutoGUI with
fuzzy image matching (confidence-based) for improved reliability.
Compatible with Ubuntu 20.04 LTS (aarch64) and XFCE desktop environment.
"""

import logging
import os
import subprocess
import time
from typing import Callable, List, Optional, Tuple

import pyautogui
import pyperclip
from PIL import Image

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# PyAutoGUI configuration
pyautogui.FAILSAFE = True  # Move mouse to corner to abort
pyautogui.PAUSE = 0.1  # Small pause between actions

# Default confidence levels to try (from high to low)
DEFAULT_CONFIDENCE_LEVELS = [0.8, 0.7, 0.6, 0.5, 0.4, 0.3]


def smart_find_image(
    image_path: str,
    confidence_levels: list = None,
    region: tuple = None,
    save_screenshot: bool = False
) -> dict:
    """
    智能查找图像模板 - 公共工具函数
    
    自动尝试不同的 confidence 级别，返回详细的调试信息。
    适用于需要调试或需要容错的场景。
    
    Args:
        image_path: 模板图像路径
        confidence_levels: 要尝试的 confidence 级别列表，默认 [0.8, 0.7, 0.6, 0.5, 0.4, 0.3]
        region: 可选的搜索区域 (x, y, width, height)
        save_screenshot: 是否保存当前屏幕截图用于调试
    
    Returns:
        dict: {
            'found': bool,           # 是否找到
            'location': tuple,       # (x, y) 坐标，未找到时为 None
            'confidence': float,     # 成功匹配的 confidence 级别
            'debug_info': str,       # 调试信息
            'screenshot_path': str,  # 截图路径（如果 save_screenshot=True）
        }
    
    Example:
        result = smart_find_image('templates/input_box.png')
        if result['found']:
            print(f"找到! 位置: {result['location']}, confidence: {result['confidence']}")
        else:
            print(f"未找到. 调试信息: {result['debug_info']}")
    """
    if confidence_levels is None:
        confidence_levels = DEFAULT_CONFIDENCE_LEVELS.copy()
    
    result = {
        'found': False,
        'location': None,
        'confidence': None,
        'debug_info': '',
        'screenshot_path': None,
    }
    
    # 检查文件是否存在
    if not os.path.exists(image_path):
        result['debug_info'] = f"模板文件不存在: {image_path}"
        logger.error(result['debug_info'])
        return result
    
    # 收集调试信息
    debug_parts = []
    debug_parts.append(f"CWD: {os.getcwd()}")
    debug_parts.append(f"DISPLAY: {os.getenv('DISPLAY', 'not set')}")
    
    try:
        screen_w, screen_h = pyautogui.size()
        debug_parts.append(f"屏幕: {screen_w}x{screen_h}")
    except Exception as e:
        debug_parts.append(f"获取屏幕尺寸失败: {e}")
    
    try:
        from PIL import Image as PILImage
        img = PILImage.open(image_path)
        debug_parts.append(f"模板: {img.size[0]}x{img.size[1]}")
    except Exception as e:
        debug_parts.append(f"读取模板失败: {e}")
    
    # 保存截图用于调试
    if save_screenshot:
        try:
            screenshot_path = "/tmp/smart_find_screenshot.png"
            screenshot = pyautogui.screenshot()
            screenshot.save(screenshot_path)
            result['screenshot_path'] = screenshot_path
            debug_parts.append(f"截图已保存: {screenshot_path}")
        except Exception as e:
            debug_parts.append(f"截图失败: {e}")
    
    # 尝试不同的 confidence 级别
    tried_levels = []
    for conf in confidence_levels:
        try:
            location = pyautogui.locateCenterOnScreen(
                image_path,
                confidence=conf,
                region=region
            )
            if location:
                result['found'] = True
                result['location'] = (location.x, location.y)
                result['confidence'] = conf
                debug_parts.append(f"成功! confidence={conf}, 位置=({location.x}, {location.y})")
                logger.info(f"smart_find_image: 找到 {image_path} @ ({location.x}, {location.y}), confidence={conf}")
                break
            else:
                tried_levels.append(f"{conf}:未找到")
        except pyautogui.ImageNotFoundException:
            tried_levels.append(f"{conf}:未找到")
        except Exception as e:
            tried_levels.append(f"{conf}:错误({e})")
    
    if not result['found']:
        debug_parts.append(f"尝试的 confidence 级别: {', '.join(tried_levels)}")
        logger.warning(f"smart_find_image: 未找到 {image_path}, 尝试了: {tried_levels}")
    
    result['debug_info'] = "; ".join(debug_parts)
    return result


def find_input_box(templates_dir: str, save_screenshot: bool = False) -> dict:
    """
    查找输入框 - 便捷公共函数
    
    专门用于查找 input_box.png 模板。
    
    Args:
        templates_dir: 模板目录路径
        save_screenshot: 是否保存截图用于调试
    
    Returns:
        smart_find_image 返回的结果字典
    """
    image_path = os.path.join(templates_dir, "input_box.png")
    return smart_find_image(image_path, save_screenshot=save_screenshot)


def activate_window(window_name_pattern: str = "antigravity") -> bool:
    """
    Activate window by name pattern using xdotool.
    
    Args:
        window_name_pattern: Window name substring to search for
        
    Returns:
        True if window found and activated, False otherwise
    """
    try:
        # Search for window ID
        # Only search for visible windows
        cmd = ['xdotool', 'search', '--onlyvisible', '--name', window_name_pattern]
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0 and result.stdout.strip():
            # Get the last window ID (usually the most relevant one if multiple)
            window_ids = result.stdout.strip().split('\n')
            target_id = window_ids[-1]
            
            # Activate window
            # --sync waits for the window to be active
            subprocess.run(['xdotool', 'windowactivate', '--sync', target_id], check=True)
            logger.info(f"Activated window '{window_name_pattern}' (ID: {target_id})")
            time.sleep(0.5) # Wait for animation/focus
            return True
        else:
            logger.warning(f"Window '{window_name_pattern}' not found")
            return False
    except Exception as e:
        logger.error(f"Error activating window '{window_name_pattern}': {e}")
        return False


def click_input_box(
    templates_dir: str,
    offset_x: int = -20,
    offset_y: int = -10,
    confidence: float = 0.8
) -> tuple:
    """
    查找并点击输入框 - 公共工具函数
    
    自动将 'antigravity' 窗口置顶，防止被遮挡。
    使用 xdotool 实现可靠的点击操作。
    
    Args:
        templates_dir: 模板目录路径
        offset_x: X轴偏移量（负值向左，默认-20）
        offset_y: Y轴偏移量（负值向上，默认-10）
        confidence: 图像匹配置信度
    
    Returns:
        tuple: (success: bool, debug_info: str)
    """
    import subprocess
    
    # 1. 尝试激活目标窗口
    activate_window("antigravity")
    
    image_path = os.path.join(templates_dir, "input_box.png")
    
    try:
        location = pyautogui.locateCenterOnScreen(image_path, confidence=confidence)
        if location:
            x = int(location.x) + offset_x
            y = int(location.y) + offset_y
            
            logger.info(f"click_input_box: 找到 input_box.png @ ({location.x}, {location.y}), 点击位置 ({x}, {y})")
            
            # 使用 xdotool 点击（更可靠）
            subprocess.run(['xdotool', 'mousemove', str(x), str(y)], check=True)
            time.sleep(0.2)
            subprocess.run(['xdotool', 'click', '1'], check=True)
            
            return True, f"点击成功 @ ({x}, {y})"
        else:
            return False, "未找到 input_box.png"
    except pyautogui.ImageNotFoundException:
        return False, "未找到 input_box.png"
    except Exception as e:
        logger.error(f"click_input_box 错误: {e}")
        return False, f"错误: {e}"


def find_replying(templates_dir: str, confidence: float = 0.9) -> tuple:
    """
    查找 Replying 指示器 - 公共工具函数
    
    Args:
        templates_dir: 模板目录路径
        confidence: 图像匹配置信度
    
    Returns:
        tuple: (found: bool, location: tuple or None)
    
    Example:
        found, location = find_replying('/path/to/templates')
        if found:
            print(f"找到Replying @ {location}")
    """
    image_path = os.path.join(templates_dir, "Replying.png")
    
    try:
        location = pyautogui.locateCenterOnScreen(image_path, confidence=confidence)
        if location:
            logger.info(f"find_replying: 找到 @ ({location.x}, {location.y})")
            return True, (int(location.x), int(location.y))
        else:
            return False, None
    except pyautogui.ImageNotFoundException:
        return False, None
    except Exception as e:
        logger.error(f"find_replying 错误: {e}")
        return False, None


def click_accept_button(templates_dir: str, confidence: float = 0.7) -> tuple:
    """
    查找并点击 Accept 或 Accept all 按钮 - 公共工具函数
    
    Args:
        templates_dir: 模板目录路径
        confidence: 图像匹配置信度
    
    Returns:
        tuple: (success: bool, debug_info: str)
    """
    import subprocess
    
    # 尝试查找的模板列表
    templates = ["accept_button.png", "accept_all.png"]
    
    for template_name in templates:
        image_path = os.path.join(templates_dir, template_name)
        
        # 跳过不存在的模板
        if not os.path.exists(image_path):
            continue
            
        try:
            location = pyautogui.locateCenterOnScreen(image_path, confidence=confidence)
            if location:
                x, y = int(location.x), int(location.y)
                
                logger.info(f"click_accept_button: 找到 {template_name} @ ({x}, {y})")
                
                # 使用 xdotool 点击
                subprocess.run(['xdotool', 'mousemove', str(x), str(y)], check=True)
                time.sleep(0.2)
                subprocess.run(['xdotool', 'click', '1'], check=True)
                
                return True, f"点击成功 ({template_name}) @ ({x}, {y})"
        except pyautogui.ImageNotFoundException:
            continue
        except Exception as e:
            logger.error(f"click_accept_button 错误 ({template_name}): {e}")
    
    return False, "未找到 accept 按钮"


def set_clipboard(text: str) -> bool:
    """
    Set text content to X11 clipboard.
    
    Args:
        text: Text to copy to clipboard
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Use xclip for X11 compatibility
        process = subprocess.Popen(
            ['xclip', '-selection', 'clipboard'],
            stdin=subprocess.PIPE,
            text=True
        )
        process.communicate(input=text)
        return process.returncode == 0
    except Exception as e:
        logger.error(f"Error setting clipboard: {e}")
        return False


from PIL import Image

# ... (rest of imports)

# ... (previous code)

def set_clipboard_image(image_path: str) -> bool:
    """
    Copy image to clipboard using xclip directly.
    Ensures image is in PNG format before copying.
    Dependencies: xclip, pillow
    
    Args:
        image_path: Path to the image file
        
    Returns:
        True if successful, False otherwise
    """
    temp_png_path = None
    try:
        if not os.path.exists(image_path):
            logger.error(f"set_clipboard_image: File not found {image_path}")
            return False
        
        abs_path = os.path.abspath(image_path)
        target_path = abs_path
        
        # 1. Ensure/Convert to PNG
        try:
            with Image.open(abs_path) as img:
                if img.format != 'PNG':
                    logger.info(f"Converting {img.format} to PNG for clipboard...")
                    # Create temporary PNG file
                    import tempfile
                    fd, temp_png_path = tempfile.mkstemp(suffix='.png')
                    os.close(fd)
                    
                    img.save(temp_png_path, format="PNG")
                    target_path = temp_png_path
                    logger.info(f"Saved temporary PNG to {target_path}")
        except Exception as e:
            logger.error(f"Error processing image format: {e}")
            # Fallback to original path if processing fails
            target_path = abs_path

        # 2. Set to Clipboard
        # Command: xclip -selection clipboard -t image/png -i /path/to/file
        cmd = ['xclip', '-selection', 'clipboard', '-t', 'image/png', '-i', target_path]
        
        env = {**os.environ, 'DISPLAY': os.getenv('DISPLAY', ':0')}
        
        # xclip stays running to serve the selection, but usually forks and exits parent.
        # Use timeout to avoid blocking if it doesn't fork correctly?
        # Added -quiet and -l 1 might help but standard usage usually works.
        # We will keep existing timeout logic.
        
        # xclip stays running to serve the selection. We must NOT wait for it to exit.
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env
        )
        
        # Wait briefly to see if it crashes immediately
        try:
            stdout, stderr = process.communicate(timeout=0.5)
            # If we are here, it exited. Check return code.
            if process.returncode == 0:
                logger.info(f"set_clipboard_image: {target_path} -> Success (xclip exited)")
                return True
            else:
                logger.error(f"set_clipboard_image: Failed (xclip) - {stderr.decode()}")
                return False
        except subprocess.TimeoutExpired:
            # It's still running, which is GOOD for xclip (holding selection)
            logger.info(f"set_clipboard_image: {target_path} -> Success (xclip running)")
            return True
            
    except Exception as e:
        logger.error(f"Error setting clipboard image (xclip): {e}")
        return False
    finally:
        # 3. Cleanup temporary file
        if temp_png_path and os.path.exists(temp_png_path):
            try:
                os.remove(temp_png_path)
                logger.debug(f"Removed temp file {temp_png_path}")
            except OSError:
                pass


def find_image(
    image_path: str,
    confidence: float = 0.8,
    region: Optional[Tuple[int, int, int, int]] = None
) -> Optional[Tuple[int, int]]:
    """
    Find an image template on screen using fuzzy matching.
    
    Args:
        image_path: Path to the template image
        confidence: Match confidence threshold (0.0 to 1.0)
        region: Optional region to search (x, y, width, height)
        
    Returns:
        Tuple of (x, y) center coordinates if found, None otherwise
    """
    try:
        if not os.path.exists(image_path):
            logger.error(f"Template image not found: {image_path}")
            return None
            
        # Try with confidence (requires opencv)
        try:
            location = pyautogui.locateCenterOnScreen(
                image_path,
                confidence=confidence,
                region=region
            )
        except pyautogui.ImageNotFoundException:
            location = None
            
        if location:
            logger.info(f"Found {image_path} at ({location.x}, {location.y})")
            return (location.x, location.y)
        else:
            logger.debug(f"Image not found on screen: {image_path}")
            return None
            
    except Exception as e:
        logger.error(f"Error finding image {image_path}: {e}")
        return None


def find_and_click(
    image_path: str,
    confidence: float = 0.8,
    offset: Tuple[int, int] = (0, 0)
) -> Tuple[bool, str]:
    """
    Find an image on screen and click it.
    
    Args:
        image_path: Path to the template image
        confidence: Match confidence threshold
        offset: (x, y) offset from found position
        
    Returns:
        Tuple of (success, debug_message)
    """
    cwd = os.getcwd()
    display = os.getenv('DISPLAY', 'not set')
    debug_msg = f"CWD: {cwd}, DISPLAY: {display}. "
    
    location = find_image(image_path, confidence)
    
    if location:
        click_x = location[0] + offset[0]
        click_y = location[1] + offset[1]
        
        logger.info(f"Found {image_path}, clicking at ({click_x}, {click_y})")
        
        pyautogui.moveTo(click_x, click_y)
        time.sleep(0.1)
        pyautogui.click()
        
        return True, "Success"
    else:
        debug_msg += f"Image '{image_path}' not found on screen."
        return False, debug_msg


def paste_and_submit():
    """Perform Ctrl+V then Enter keystrokes."""
    logger.info("PasteAndSubmit: Sending Ctrl+V...")
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.2)
    
    logger.info("PasteAndSubmit: Sending Enter...")
    pyautogui.press('return')


def monitor_process(
    replying_img: str,
    accept_img: str,
    on_thinking: Optional[Callable[[], None]] = None,
    confidence: float = 0.8,
    accept_confidence: float = 0.6
):
    """
    Monitor the reply process and interact as needed.
    
    This function:
    1. Waits for "Replying" indicator to appear
    2. Monitors the process, clicking "Accept" button when it appears
    3. Sends "Thinking..." status periodically
    4. Exits when "Replying" indicator disappears
    
    Args:
        replying_img: Path to "Replying" indicator template
        accept_img: Path to accept button template
        on_thinking: Callback to invoke when sending thinking status
        confidence: Image matching confidence threshold for replying indicator
        accept_confidence: Confidence threshold for accept button (default 0.6)
    """
    logger.info("MonitorProcess: Starting loop...")
    
    # Phase 1: Wait for Replying to appear (Max 10s)
    logger.info("MonitorProcess: Waiting for 'Replying' to appear...")
    appeared = False
    start_time = time.time()
    
    while time.time() - start_time < 10:
        if find_image(replying_img, confidence):
            logger.info("MonitorProcess: 'Replying' detected! Entering monitor loop.")
            appeared = True
            break
        time.sleep(0.5)
    
    if not appeared:
        logger.info("MonitorProcess: 'Replying' never appeared. Assuming finished or missed.")
        return
    
    # Phase 2: Monitor Loop
    last_thinking_time = time.time()
    not_found_count = 0
    max_not_found = 5
    timeout = 300  # 5 minutes safety timeout
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        time.sleep(1)
        
        # Check if Replying indicator is still present
        if not find_image(replying_img, confidence):
            not_found_count += 1
            logger.info(f"MonitorProcess: 'Replying' not found ({not_found_count}/{max_not_found})")
            
            if not_found_count >= max_not_found:
                logger.info("MonitorProcess: 'Replying' gone. Stopping loop.")
                return
            continue
        
        # Reset counter as we found it
        not_found_count = 0
        
        # Send Thinking status every 5 seconds
        if time.time() - last_thinking_time >= 5:
            if on_thinking:
                logger.info("MonitorProcess: Sending 'Thinking...'")
                on_thinking()
            last_thinking_time = time.time()
        
        # Check and click Accept button (uses lower confidence)
        if find_image(accept_img, accept_confidence):
            logger.info("MonitorProcess: Found Accept button. Clicking...")
            find_and_click(accept_img, accept_confidence)
    
    logger.info("MonitorProcess: Safety timeout reached.")


def full_workflow(
    text: str,
    templates_dir: str,
    send_status: Callable[[str], None],
    confidence: float = 0.8
):
    """
    执行完整的文字消息工作流:
    
    流程:
    1. 复制文本到剪贴板
    2. click_input_box() 点击输入框
    3. Ctrl+V 粘贴
    4. Enter 提交
    5. find_replying() 检测 Replying 状态
    6. 如果找到 Replying，每5秒:
       - 发送 "思考中..." 状态
       - click_accept_button() 点击 Accept 按钮
    
    Args:
        text: 要发送的文本内容
        templates_dir: 模板目录路径
        send_status: 发送状态消息的回调函数
        confidence: 图像匹配置信度
    """
    # 1. 复制文本到剪贴板
    if not set_clipboard(text):
        logger.error("Error setting clipboard")
        send_status("错误: 无法复制到剪贴板")
        return
    
    # 2. 点击输入框
    success, debug_info = click_input_box(templates_dir)
    if not success:
        logger.error(f"Could not click input_box: {debug_info}")
        send_status(f"错误: 无法点击输入框. {debug_info}")
        return
    
    # 3. Ctrl+V 粘贴
    time.sleep(0.3)
    logger.info("粘贴文本...")
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.3)
    
    # 4. Enter 提交
    logger.info("提交...")
    pyautogui.press('return')
    
    # 5. 检测 Replying 状态
    logger.info("等待 Replying 出现...")
    appeared = False
    start_time = time.time()
    
    while time.time() - start_time < 10:
        found, _ = find_replying(templates_dir)  # 使用默认 confidence=0.9
        if found:
            logger.info("检测到 Replying!")
            appeared = True
            break
        time.sleep(0.5)
    
    if not appeared:
        logger.info("Replying 未出现，任务可能已完成")
        return
    
    # 6. 监控循环
    last_action_time = time.time()
    not_found_count = 0
    max_not_found = 5
    timeout = 300
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        time.sleep(1)
        
        # 检查 Replying 是否还在
        found, _ = find_replying(templates_dir)  # 使用默认 confidence=0.9
        if not found:
            not_found_count += 1
            logger.info(f"Replying 未找到 ({not_found_count}/{max_not_found})")
            if not_found_count >= max_not_found:
                logger.info("Replying 消失，任务完成")
                return
            continue
        
        not_found_count = 0
        
        # 每5秒执行一次
        if time.time() - last_action_time >= 5:
            # 1) 发送 "思考中..." 状态
            logger.info("发送状态: 思考中...")
            send_status("思考中...")
            
            # 2) 点击 Accept 按钮
            success, info = click_accept_button(templates_dir)
            if success:
                logger.info(f"Accept 按钮已点击: {info}")
            
            last_action_time = time.time()
    
    logger.info("监控超时")


def full_workflow_image(
    image_path: str,
    templates_dir: str,
    send_status: Callable[[str], None],
    confidence: float = 0.8
):
    """
    Execute the full image workflow:
    1. Copy image to clipboard
    2. Find and click input box
    3. Paste and submit
    4. Monitor process
    """
    # 1. Copy Image to Clipboard
    if not set_clipboard_image(image_path):
        logger.error(f"Error setting clipboard image: {image_path}")
        send_status(f"Error setting clipboard image: {image_path}")
        return
    
    # 2. Find Input Box
    input_box_img = os.path.join(templates_dir, "input_box.png")
    success, debug_log = find_and_click(input_box_img, confidence)
    
    if success:
        # 3. Paste and Submit
        paste_and_submit()
        
        # 4. Monitor Process
        replying_img = os.path.join(templates_dir, "Replying.png")
        accept_img = os.path.join(templates_dir, "accept_button.png")
        
        monitor_process(
            replying_img,
            accept_img,
            on_thinking=lambda: send_status("Thinking..."),
            confidence=confidence
        )
    else:
        logger.error("Could not find input_box.png")
        send_status(f"Error [v3]: input_box.png (img flow) not found. Info: {debug_log}")


def full_workflow_media_group(
    image_paths: List[str],
    text: str,
    templates_dir: str,
    send_status: Callable[[str], None],
    confidence: float = 0.8,
    file_paths: List[str] = None
):
    """
    执行完整的多图+文字+文件消息工作流:
    
    流程:
    1. 对于每张图片:
       - 复制图片到剪贴板
       - click_input_box() 点击输入框
       - Ctrl+V 粘贴
    2. 对于每个文件:
       - 复制 "@/path/to/file" 格式到剪贴板
       - click_input_box() 点击输入框
       - Ctrl+V 粘贴
    3. 复制文字到剪贴板
    4. click_input_box() 点击输入框
    5. Ctrl+V 粘贴
    6. Enter 提交
    7. find_replying() 检测 Replying 状态
    8. 如果找到 Replying，每5秒:
       - 发送 "思考中..." 状态
       - click_accept_button() 点击 Accept 按钮
    
    Args:
        image_paths: 图片路径列表
        text: 文字内容
        templates_dir: 模板目录路径
        send_status: 发送状态消息的回调函数
        confidence: 图像匹配置信度
        file_paths: 非图片文件路径列表
    """
    if file_paths is None:
        file_paths = []
    # 1. 处理每张图片
    for i, img_path in enumerate(image_paths):
        logger.info(f"处理图片 {i+1}/{len(image_paths)}: {img_path}")
        
        # 复制图片到剪贴板
        if not set_clipboard_image(img_path):
            logger.error(f"无法复制图片到剪贴板: {img_path}")
            send_status(f"错误: 无法复制图片 {i+1}")
            continue
        
        # 点击输入框
        success, debug_info = click_input_box(templates_dir)
        if not success:
            logger.error(f"无法点击输入框: {debug_info}")
            send_status(f"错误: 无法点击输入框. {debug_info}")
            return
        
        # Ctrl+V 粘贴
        time.sleep(0.3)
        logger.info("粘贴图片...")
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)
    
    # 2. 处理每个非图片文件（使用 @路径 格式）
    for i, file_path in enumerate(file_paths):
        logger.info(f"处理文件 {i+1}/{len(file_paths)}: {file_path}")
        
        # 获取绝对路径并构造 @路径 格式
        abs_path = os.path.abspath(file_path)
        file_ref = f"@{abs_path}"
        
        # 复制 @路径 到剪贴板
        if not set_clipboard(file_ref):
            logger.error(f"无法复制文件路径到剪贴板: {file_ref}")
            send_status(f"错误: 无法复制文件 {i+1}")
            continue
        
        # 点击输入框
        success, debug_info = click_input_box(templates_dir)
        if not success:
            logger.error(f"无法点击输入框: {debug_info}")
            send_status(f"错误: 无法点击输入框. {debug_info}")
            return
        
        # Ctrl+V 粘贴
        time.sleep(0.3)
        logger.info(f"粘贴文件路径: {file_ref}")
        pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.5)
    
    # 3-5. 处理文字
    if text:
        logger.info("处理文字内容")
        
        # 复制文字到剪贴板
        if not set_clipboard(text):
            logger.error("无法复制文字到剪贴板")
            send_status("错误: 无法复制文字")
        else:
            # 点击输入框
            success, debug_info = click_input_box(templates_dir)
            if not success:
                logger.error(f"无法点击输入框: {debug_info}")
                send_status(f"错误: 无法点击输入框. {debug_info}")
                return
            
            # Ctrl+V 粘贴
            time.sleep(0.3)
            logger.info("粘贴文字...")
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.3)
    
    # 5. Enter 提交
    logger.info("等待上传稳定...")
    time.sleep(2)
    logger.info("提交...")
    pyautogui.press('return')
    
    # 6. 检测 Replying 状态
    logger.info("等待 Replying 出现...")
    appeared = False
    start_time = time.time()
    
    while time.time() - start_time < 10:
        found, _ = find_replying(templates_dir)  # 使用默认 confidence=0.9
        if found:
            logger.info("检测到 Replying!")
            appeared = True
            break
        time.sleep(0.5)
    
    if not appeared:
        logger.info("Replying 未出现，任务可能已完成")
        return
    
    # 7. 监控循环
    last_action_time = time.time()
    not_found_count = 0
    max_not_found = 5
    timeout = 300
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        time.sleep(1)
        
        # 检查 Replying 是否还在
        found, _ = find_replying(templates_dir)  # 使用默认 confidence=0.9
        if not found:
            not_found_count += 1
            logger.info(f"Replying 未找到 ({not_found_count}/{max_not_found})")
            if not_found_count >= max_not_found:
                logger.info("Replying 消失，任务完成")
                return
            continue
        
        not_found_count = 0
        
        # 每5秒执行一次
        if time.time() - last_action_time >= 5:
            # 1) 发送 "思考中..." 状态
            logger.info("发送状态: 思考中...")
            send_status("思考中...")
            
            # 2) 点击 Accept 按钮
            success, info = click_accept_button(templates_dir)
            if success:
                logger.info(f"Accept 按钮已点击: {info}")
            
            last_action_time = time.time()
    
    logger.info("监控超时")
