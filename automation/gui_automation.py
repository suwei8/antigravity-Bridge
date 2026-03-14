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

import pyperclip
from PIL import Image

# Lazy import for pyautogui — it connects to X11 on import,
# which crashes if DISPLAY is invalid (e.g. stale SSH X11 forwarding)
pyautogui = None


def _fix_display():
    """Validate current DISPLAY and auto-fix if broken.
    
    Checks if the current DISPLAY env var points to a live X server.
    If not, scans /tmp/.X11-unix/ sockets and common display numbers
    to find a working one. Updates os.environ['DISPLAY'] in-place.
    """
    import subprocess as _sp
    import glob

    current = os.environ.get('DISPLAY', '')

    # Quick check: is current DISPLAY valid?
    def _is_valid(d):
        if not d:
            return False
        try:
            r = _sp.run(
                ['xdpyinfo'],
                env={**os.environ, 'DISPLAY': d},
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL,
                timeout=3
            )
            return r.returncode == 0
        except Exception:
            return False

    if _is_valid(current):
        return  # Current DISPLAY works fine

    logging.getLogger(__name__).warning(
        f"DISPLAY={current!r} is not reachable, scanning for valid X11 display..."
    )

    # Build candidate list: X11 sockets first, then common fallbacks
    candidates = []
    for sock in sorted(glob.glob('/tmp/.X11-unix/X*')):
        num = sock.rsplit('X', 1)[-1]
        candidates.append(f':{num}')

    for fallback in [':0', ':1', ':2']:
        if fallback not in candidates:
            candidates.append(fallback)

    for candidate in candidates:
        if _is_valid(candidate):
            os.environ['DISPLAY'] = candidate
            logging.getLogger(__name__).info(
                f"Auto-fixed DISPLAY: {current!r} -> {candidate!r}"
            )
            return

    logging.getLogger(__name__).error(
        f"No valid X11 display found (tried: {candidates}). GUI operations will fail."
    )


def _ensure_pyautogui():
    """Lazily import pyautogui on first use, after validating DISPLAY."""
    global pyautogui
    if pyautogui is None:
        _fix_display()
        import pyautogui as _pyautogui
        pyautogui = _pyautogui
        pyautogui.FAILSAFE = True
        pyautogui.PAUSE = 0.1
    return pyautogui

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

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
    _ensure_pyautogui()
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
    _ensure_pyautogui()
    
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
    _ensure_pyautogui()
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
    
    _ensure_pyautogui()
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
        # 优先使用 pyperclip，它处理得更好
        pyperclip.copy(text)
        return True
    except Exception as e:
        logger.warning(f"pyperclip failed, falling back to xclip: {e}")
        try:
            # Fallback to xclip
            process = subprocess.Popen(
                ['xclip', '-selection', 'clipboard'],
                stdin=subprocess.PIPE,
                text=True
            )
            process.communicate(input=text, timeout=2)
            return process.returncode == 0
        except Exception as e2:
            logger.error(f"Error setting clipboard: {e2}")
            return False


from PIL import Image

# ... (rest of imports)

# ... (previous code)

def set_clipboard_image(image_path: str) -> Tuple[bool, Optional[subprocess.Popen]]:
    """
    Copy image to clipboard using xclip directly.
    Ensures image is in PNG format before copying.
    Dependencies: xclip, pillow
    
    Args:
        image_path: Path to the image file
        
    Returns:
        Tuple[bool, Optional[subprocess.Popen]]: (Success, Process object if running)
        NOTE: If successful, the xclip process is returned and MUST be terminated
              by the caller after pasting is complete to release the clipboard.
    """
    temp_png_path = None
    try:
        if not os.path.exists(image_path):
            logger.error(f"set_clipboard_image: File not found {image_path}")
            return False, None
        
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
        
        # xclip stays running to serve the selection. We must NOT wait for it to exit.
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env
        )
        
        # Wait briefly to see if it crashes immediately
        try:
            # Wait a tiny bit to check for immediate failure
            # But xclip SHOULD block, so TimeoutExpired is expected (and good)
            process.wait(timeout=0.1)
            
            # If we are here, it exited. Check return code.
            if process.returncode != 0:
                stderr = process.stderr.read() if process.stderr else b""
                logger.error(f"set_clipboard_image: Failed (xclip exited) - {stderr.decode()}")
                return False, None
                
            # If it exited with 0 immediately, that's weird for xclip without -l 1,
            # but maybe it forked? xclip usually doesn't fork by default unless backgrounded.
            return True, None # It's gone, no process to manage
            
        except subprocess.TimeoutExpired:
            # It's still running, which is GOOD for xclip (holding selection)
            logger.info(f"set_clipboard_image: {target_path} -> Success (xclip running)")
            return True, process
            
    except Exception as e:
        logger.error(f"Error setting clipboard image (xclip): {e}")
        return False, None
    finally:
        # 3. Cleanup temporary file
        # 注意：如果 xclip 还在运行且使用了 temp file，这一步可能会导致问题？
        # xclip 需要读取文件内容。通常它会读取进内存吗？
        # xclip 读取文件应该很快。
        if temp_png_path and os.path.exists(temp_png_path):
            try:
                # 稍微延迟删除，确保 xclip以此读取
                time.sleep(0.2) 
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
    _ensure_pyautogui()
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
        
        try:
            import subprocess
            subprocess.run(['xdotool', 'mousemove', str(int(click_x)), str(int(click_y))], check=True)
            time.sleep(0.1)
            subprocess.run(['xdotool', 'click', '1'], check=True)
        except Exception as e:
            logger.warning(f"xdotool click failed: {e}. Falling back to pyautogui.")
            pyautogui.moveTo(click_x, click_y)
            time.sleep(0.1)
            pyautogui.click()
        
        return True, "Success"
    else:
        debug_msg += f"Image '{image_path}' not found on screen."
        return False, debug_msg


def paste_and_submit():
    """Perform Ctrl+V then Enter keystrokes."""
    _ensure_pyautogui()
    logger.info("PasteAndSubmit: Sending Ctrl+V...")
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.2)
    
    logger.info("PasteAndSubmit: Sending Enter...")
    pyautogui.press('return')


def handle_model_switch(templates_dir: str, reply_event=None, send_status: Optional[Callable[[str], None]] = None) -> str:
    """
    检查模型配额耗尽并自动尝试切换模型（执行一次 continue）。
    
    采用全屏查找 + pynput 鼠标点击的稳健方案（已通过 debug_find_pane.py 验证）。
    
    返回状态:
    - "NOT_FOUND": 未发现 Upgrade 弹窗
    - "UPGRADE_DETECTED": 发现 Upgrade 弹窗但切换未成功（面板/目标模型未找到）
    - "SWITCHED:*": 成功点击了备用模型并输入了 continue
    """
    
    _ensure_pyautogui()
    # 1. 在整个屏幕上查找 "Upgrade.png" 和 "Upgrade2.png"，"Upgrade3.png"找到任意一个才触发切换
    upgrade_found = False
    for template in ["Upgrade.png", "Upgrade2.png", "Upgrade3.png"]:
        res = smart_find_image(os.path.join(templates_dir, template), confidence_levels=[0.8])
        if res.get('found'):
            upgrade_found = True
            logger.info(f"升级弹窗识别成功: {template}, confidence: {res.get('confidence')}")
            break
            
    if not upgrade_found:
        return "NOT_FOUND"
        
    logger.info("检测到 Upgrade 弹窗，开始处理单次模型切换")
    from pynput.mouse import Controller, Button
    mouse = Controller()
    
    time.sleep(1)
    
    # 2. 全屏查找面板（与 debug_find_pane.py 一致，不使用 region 限制）
    panel_opus = os.path.join(templates_dir, "panel-ClaudeOpus.png")
    panel_gemini = os.path.join(templates_dir, "panel-Gemini.png")

    found_panel = None
    panel_loc = None

    # 查找 panel-ClaudeOpus.png（全屏，confidence=0.8）
    for conf in [0.8]:
        try:
            loc = pyautogui.locateCenterOnScreen(panel_opus, confidence=conf)
            if loc:
                found_panel = "opus"
                panel_loc = (int(loc.x), int(loc.y))
                logger.info(f"✅ 找到 panel-ClaudeOpus.png @ {panel_loc}, confidence={conf}")
                break
        except pyautogui.ImageNotFoundException:
            pass

    # 查找 panel-Gemini.png（全屏，confidence=0.8）
    if not found_panel:
        for conf in [0.8]:
            try:
                loc = pyautogui.locateCenterOnScreen(panel_gemini, confidence=conf)
                if loc:
                    found_panel = "gemini"
                    panel_loc = (int(loc.x), int(loc.y))
                    logger.info(f"✅ 找到 panel-Gemini.png @ {panel_loc}, confidence={conf}")
                    break
            except pyautogui.ImageNotFoundException:
                pass
        
    if not found_panel:
        logger.warning("❌ 全屏查找均未找到面板")
        try:
            screenshot_path = os.path.join(os.getcwd(), "failed_find_panel.png")
            pyautogui.screenshot().save(screenshot_path)
            logger.info(f"✅ 已保存现场截图至: {screenshot_path}")
        except Exception as e:
            logger.error(f"❌ 现场截图保存失败: {e}")
        return "UPGRADE_DETECTED"
        
    # 3. 点击面板（向下偏移 10px，使用 pynput mouse）
    px, py = panel_loc
    logger.info(f"🖱️ 移动鼠标到 ({px}, {py + 10}) 并点击...")
    time.sleep(1)
    mouse.position = (px, py + 10)
    time.sleep(1)
    mouse.click(Button.left, 1)
    logger.info("✅ 面板点击完成")

    # 4. 延迟 3 秒等待下拉菜单展开，然后全屏查找目标模型
    time.sleep(3)

    if found_panel == "opus":
        # A情况：当前是 Claude Opus，切换到 Gemini
        target_img = os.path.join(templates_dir, "Gemini3.1Pro-High.png")
        target_name = "Gemini3.1 Pro High"
        logger.info("A情况：找到 panel-ClaudeOpus.png，查找 Gemini3.1Pro-High.png...")
    else:
        # B情况：当前是 Gemini，切换到 Claude Opus
        target_img = os.path.join(templates_dir, "Claude-Opus-4.6-Thinking.png")
        target_name = "Claude Opus 4.6 Thinking"
        logger.info("B情况：找到 panel-Gemini.png，查找 Claude-Opus-4.6-Thinking.png...")

    # 全屏查找目标模型（confidence=0.8，与 debug 脚本一致）
    target_loc = None
    for conf in [0.8]:
        try:
            loc = pyautogui.locateCenterOnScreen(target_img, confidence=conf)
            if loc:
                target_loc = (int(loc.x), int(loc.y))
                logger.info(f"✅ 找到 {os.path.basename(target_img)} @ {target_loc}, confidence={conf}")
                break
        except pyautogui.ImageNotFoundException:
            pass

    if not target_loc:
        logger.error(f"❌ 未找到 {os.path.basename(target_img)}，流程中断")
        return "UPGRADE_DETECTED"

    # 5. 点击目标模型
    tx, ty = target_loc
    mouse.position = (tx, ty)
    time.sleep(1)
    mouse.click(Button.left, 1)
    logger.info(f"✅ {target_name} 点击完成")

    # 6. 延迟 1 秒，执行 continue（直接粘贴 + 回车，与 debug 脚本一致）
    time.sleep(1)
    set_clipboard("continue")
    time.sleep(0.2)
    pyautogui.hotkey('ctrl', 'v')
    time.sleep(0.3)
    pyautogui.press('return')
    logger.info("✅ continue 已提交")

    # 7. 发送 TG 通知
    time.sleep(1)
    if send_status:
        send_status(f"🔄 模型已切换为: {target_name}")

    return f"SWITCHED:{target_name}"


def _check_retry(templates_dir: str) -> bool:
    """
    检查并点击 Retry 按钮（IDE 网络断开时弹出）。
    
    Returns:
        True 如果找到并点击了 Retry 按钮
    """
    retry_img = os.path.join(templates_dir, "Retry.png")
    success, debug_info = find_and_click(retry_img, confidence=0.8, offset=(0, 0))
    if success:
        logger.info(f"_check_retry: Retry 按钮已点击: {debug_info}")
        return True
    return False


def monitor_process(
    templates_dir: str,
    send_status: Optional[Callable[[str], None]] = None,
    reply_event=None
):
    """
    监控 IDE 回复过程，按三阶段模型运行：
    
    阶段 1: 等待 Replying 出现（最多 5 秒，纯等待无监控）
    阶段 2: Replying 可见期间（Accept + 心跳消息，每 10 秒）
    阶段 3: Replying 消失后 3 秒缓冲，统一检测 Retry / Upgrade
    """
    logger.info("MonitorProcess: Starting...")
    timeout = 300  # 总超时 5 分钟
    overall_start = time.time()
    
    while time.time() - overall_start < timeout:
        # ========== 阶段 1: 纯等待 Replying 出现（最多 5 秒） ==========
        logger.info("MonitorProcess [阶段1]: 等待 Replying 出现...")
        appeared = False
        phase1_start = time.time()
        
        while time.time() - phase1_start < 5:
            if reply_event and reply_event.is_set():
                logger.info("MonitorProcess [阶段1]: reply_event 已 set，停止。")
                return
            
            found, _ = find_replying(templates_dir)
            if found:
                logger.info("MonitorProcess [阶段1]: Replying 已出现！进入阶段 2。")
                appeared = True
                break
            time.sleep(0.5)
        
        if not appeared:
            # Replying 从未出现 → 等同于"Replying 消失"，直接进入阶段 3
            logger.info("MonitorProcess [阶段1]: 5 秒内未见 Replying，进入阶段 3 检测。")
            # 跳到阶段 3（下方）
        else:
            # ========== 阶段 2: Replying 可见，IDE 正常工作中 ==========
            logger.info("MonitorProcess [阶段2]: IDE 工作中，启动 Accept + 心跳监控。")
            last_heartbeat_time = time.time()
            not_found_count = 0
            
            while time.time() - overall_start < timeout:
                if reply_event and reply_event.is_set():
                    logger.info("MonitorProcess [阶段2]: reply_event 已 set，IDE 已回复。停止。")
                    return
                
                time.sleep(1)
                
                found, _ = find_replying(templates_dir)
                if found:
                    # Replying 仍然可见，复位消失计数
                    not_found_count = 0
                    
                    # 每 10 秒：Accept 点击 + 心跳消息
                    if time.time() - last_heartbeat_time >= 10:
                        # 发送心跳消息
                        if send_status:
                            current_time = time.strftime("%H:%M:%S", time.localtime())
                            logger.info(f"MonitorProcess [阶段2]: 心跳 ({current_time})")
                            send_status(f"思考中...({current_time})")
                        # 尝试点击 Accept 按钮
                        success, info = click_accept_button(templates_dir)
                        if success:
                            logger.info(f"MonitorProcess [阶段2]: Accept 已点击: {info}")
                        last_heartbeat_time = time.time()
                else:
                    # Replying 不可见
                    not_found_count += 1
                    logger.info(f"MonitorProcess [阶段2]: Replying 不可见 ({not_found_count}/3)")
                    
                    if not_found_count >= 3:
                        # 消失超过 3 秒 → 进入阶段 3
                        logger.info("MonitorProcess [阶段2]: Replying 已消失 3 秒，进入阶段 3 检测。")
                        break
            else:
                # 总超时退出
                logger.warning("MonitorProcess [阶段2]: 总超时 300 秒，退出。")
                return
        
        # ========== 阶段 3: 关键判断点 - 统一检测 Retry / Upgrade ==========
        if reply_event and reply_event.is_set():
            logger.info("MonitorProcess [阶段3]: reply_event 已 set，停止。")
            return
        
        logger.info("MonitorProcess [阶段3]: 开始检测 Retry / Upgrade...")
        
        # 3a. 检查 Retry 按钮（网络断开）
        if _check_retry(templates_dir):
            logger.info("MonitorProcess [阶段3]: 发现 Retry，已点击恢复。等待 3 秒后回到阶段 1...")
            time.sleep(3)
            continue  # 回到阶段 1
        
        # 3b. 检查 Upgrade 弹窗（配额耗尽）
        switch_status = handle_model_switch(templates_dir, reply_event, send_status)
        if switch_status and switch_status.startswith("SWITCHED"):
            switched_to = switch_status.split(":", 1)[1] if ":" in switch_status else "未知模型"
            logger.info(f"MonitorProcess [阶段3]: 配额耗尽，已切换模型至 {switched_to} + 发送 continue。等待 5 秒后复检...")
            time.sleep(5)
            
            # 复检：切换后 Upgrade 弹窗是否仍然存在
            still_upgrade = False
            for template in ["Upgrade.png", "Upgrade2.png", "Upgrade3.png"]:
                res = smart_find_image(os.path.join(templates_dir, template), confidence_levels=[0.8])
                if res.get('found'):
                    still_upgrade = True
                    break
            
            if still_upgrade:
                # 所有模型配额都耗尽了，停止循环
                logger.warning("MonitorProcess [阶段3]: 切换后仍检测到 Upgrade，所有模型配额已耗尽。退出。")
                if send_status:
                    send_status("⚠️ 所有模型配额已耗尽，停止重试。")
                return
            else:
                # 新模型正常工作，继续监控
                logger.info("MonitorProcess [阶段3]: 切换后 Upgrade 已消失，新模型正常。回到阶段 1...")
                continue  # 回到阶段 1
        
        # 3b-retry. Upgrade 已发现但切换未完成（面板/目标模型没找到），等待后重试
        if switch_status == "UPGRADE_DETECTED":
            logger.warning("MonitorProcess [阶段3]: Upgrade 弹窗存在但切换失败，5 秒后重试...")
            time.sleep(5)
            continue  # 回到阶段 1 重试
        
        # 3c. 都没找到 → IDE 正常结束工作
        logger.info("MonitorProcess [阶段3]: 未发现 Retry/Upgrade，IDE 正常完成工作。退出。")
        return
    
    logger.warning("MonitorProcess: 总超时 300 秒，退出。")
    



def full_workflow(
    text: str,
    templates_dir: str,
    send_status: Callable[[str], None],
    confidence: float = 0.8,
    reply_event=None
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
    7. 当 reply_event 被 set 时立即停止
    
    Args:
        text: 要发送的文本内容
        templates_dir: 模板目录路径
        send_status: 发送状态消息的回调函数
        confidence: 图像匹配置信度
        reply_event: threading.Event, MCP 回复后 set, 停止思考中
    """
    _ensure_pyautogui()
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
    
    # 5. 监控循环
    monitor_process(templates_dir, send_status, reply_event)


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
    success, clip_process = set_clipboard_image(image_path)
    if not success:
        logger.error(f"Error setting clipboard image: {image_path}")
        send_status(f"Error setting clipboard image: {image_path}")
        return
    
    try:
        # 2. Find Input Box
        input_box_img = os.path.join(templates_dir, "input_box.png")
        success, debug_log = find_and_click(input_box_img, confidence)
        
        if success:
            # 3. Paste and Submit
            paste_and_submit()
            
            # 4. Monitor Process
            monitor_process(templates_dir, send_status, reply_event=None)
        else:
            logger.error("Could not find input_box.png")
            send_status(f"Error [v3]: input_box.png (img flow) not found. Info: {debug_log}")
            
    finally:
        # Cleanup clipboard process ALWAYS
        if clip_process:
            logger.debug("Cleaning up xclip process...")
            try:
                clip_process.terminate()
                clip_process.wait(timeout=1)
            except Exception as e:
                logger.warning(f"Error cleaning up xclip: {e}")


def full_workflow_media_group(
    image_paths: List[str],
    text: str,
    templates_dir: str,
    send_status: Callable[[str], None],
    confidence: float = 0.8,
    file_paths: List[str] = None,
    reply_event=None
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
    9. 当 reply_event 被 set 时立即停止
    
    Args:
        image_paths: 图片路径列表
        text: 文字内容
        templates_dir: 模板目录路径
        send_status: 发送状态消息的回调函数
        confidence: 图像匹配置信度
        file_paths: 非图片文件路径列表
        reply_event: threading.Event, MCP 回复后 set, 停止思考中
    """
    _ensure_pyautogui()
    if file_paths is None:
        file_paths = []
    # 1. 处理每张图片
    for i, img_path in enumerate(image_paths):
        logger.info(f"处理图片 {i+1}/{len(image_paths)}: {img_path}")
        
        # 复制图片到剪贴板
        success, clip_process = set_clipboard_image(img_path)
        if not success:
            logger.error(f"无法复制图片到剪贴板: {img_path}")
            send_status(f"错误: 无法复制图片 {i+1}")
            continue
            
        try:
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
            
        finally:
            # Cleanup clipboard process ALWAYS
            if clip_process:
                try:
                    clip_process.terminate()
                    clip_process.wait(timeout=1)
                except:
                    pass
    
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
    
    # 6. 监控循环
    monitor_process(templates_dir, send_status, reply_event)
