import os
import subprocess
import threading
import re
import logging

logger = logging.getLogger(__name__)

class CLIBridge:
    """
    Manages a CLI agent tool (like Codex CLI) by executing each user message
    as a non-interactive subprocess using `codex exec`.
    
    Instead of maintaining a persistent TUI REPL (which Codex doesn't support
    cleanly via PTY), each Telegram message triggers a fresh `codex exec` call
    with the user's prompt, and the output is streamed back to Telegram.
    """
    def __init__(self, command: str, send_telegram_callback):
        self.base_command = command  # e.g. "/home/sw/.nvm/versions/node/v24.13.0/bin/codex"
        # Strip --no-alt-screen if present (not needed for exec mode)
        self.base_command = self.base_command.replace(" --no-alt-screen", "")
        self.send_telegram = send_telegram_callback
        self.running = True
        self.current_process = None
        self.lock = threading.Lock()
        self.cwd = os.getenv("CLI_CWD", "/home/sw/dev_root/")  # Default working directory
        # ANSI escape code stripper
        self.ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        
    def start(self):
        """Mark the bridge as ready. No persistent process needed."""
        self.running = True
        logger.info(f"CLIBridge initialized (exec mode) with command: {self.base_command}")
    
    def set_cwd(self, path: str) -> str:
        """Set the working directory for CLI exec. Returns status message."""
        expanded = os.path.expanduser(path)
        if os.path.isdir(expanded):
            self.cwd = expanded
            logger.info(f"CLI working directory set to: {expanded}")
            return f"✅ 工作目录已切换到: {expanded}"
        else:
            return f"❌ 目录不存在: {expanded}"
    
    def send_input(self, text: str):
        """
        Execute the user's prompt via `codex exec` in a background thread.
        Each message spawns a new subprocess.
        """
        if not self.running:
            logger.warning("CLIBridge is not running.")
            try:
                self.send_telegram("❌ CLI Bridge 未启动。")
            except:
                pass
            return
        
        # Run in a background thread to avoid blocking the Telegram handler
        thread = threading.Thread(target=self._execute_prompt, args=(text,), daemon=True)
        thread.start()
        
    def _execute_prompt(self, prompt: str):
        """Execute a single prompt via codex exec and send output to Telegram."""
        # Build command: codex exec "prompt" --full-auto
        cmd = [
            self.base_command,
            "exec",
            prompt,
            "--full-auto",
        ]
        # Use -C to set working directory for codex
        cd_flag = f' -C {repr(self.cwd)}' if self.cwd else ''
        cmd_str = f'{self.base_command} exec {repr(prompt)} --full-auto --skip-git-repo-check{cd_flag}'
        
        logger.info(f"CLI exec: {cmd_str}")
        
        try:
            # Notify user that we're processing
            try:
                self.send_telegram("⏳ 正在处理你的请求...")
            except:
                pass
            
            process = subprocess.Popen(
                cmd_str,
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=os.path.expanduser("~"),
                env={**os.environ, "TERM": "dumb", "NO_COLOR": "1"},
            )
            
            with self.lock:
                self.current_process = process
            
            # Read output
            output_lines = []
            try:
                stdout, _ = process.communicate(timeout=300)  # 5 min timeout
                if stdout:
                    raw_text = stdout.decode('utf-8', errors='replace')
                    # Strip ANSI codes
                    clean_text = self.ansi_escape.sub('', raw_text)
                    output_lines = clean_text.strip().split('\n')
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
                try:
                    self.send_telegram("⏰ 命令执行超时 (5分钟)，已终止。")
                except:
                    pass
                return
            finally:
                with self.lock:
                    self.current_process = None
            
            # Parse and filter the output
            # Codex exec output format:
            # - Header lines (OpenAI Codex v..., workdir, model, etc.)
            # - "user" + the prompt
            # - "codex" + the response
            # - "tokens used" + count
            # We want to extract only the meaningful response
            
            result_text = self._parse_codex_output(output_lines)
            
            if result_text:
                logger.info(f"CLI exec result: {result_text[:200]}...")
                # Split long messages for Telegram (4096 char limit)
                for chunk in self._split_message(result_text, 4000):
                    try:
                        self.send_telegram(chunk)
                    except Exception as e:
                        logger.error(f"Error sending CLI output to Telegram: {e}")
            else:
                logger.warning(f"CLI exec produced no parseable output. Raw lines: {len(output_lines)}")
                # Send raw output if we couldn't parse it
                raw_output = '\n'.join(output_lines[-20:])  # Last 20 lines
                if raw_output.strip():
                    try:
                        self.send_telegram(raw_output.strip())
                    except Exception as e:
                        logger.error(f"Error sending raw CLI output: {e}")
                        
        except Exception as e:
            logger.error(f"CLI exec error: {e}")
            try:
                self.send_telegram(f"❌ 执行出错: {str(e)}")
            except:
                pass
    
    def _parse_codex_output(self, lines):
        """
        Parse codex exec output to extract only the agent's response.
        
        The output format is roughly:
        OpenAI Codex v0.114.0 (research preview)
        --------
        workdir: ...
        model: ...
        ... (header)
        --------
        user
        <user prompt>
        codex
        <agent thinking/reasoning>
        codex
        <agent response>
        tokens used
        <count>
        """
        # Find the content between the last "codex" marker and "tokens used"
        result_parts = []
        in_codex_response = False
        skip_header = True
        header_end_count = 0
        
        for line in lines:
            stripped = line.strip()
            
            # Skip the header block (ends after second "--------")
            if skip_header:
                if stripped == "--------":
                    header_end_count += 1
                    if header_end_count >= 2:
                        skip_header = False
                continue
            
            # Skip the "user" section and user's prompt echo
            if stripped == "user":
                in_codex_response = False
                continue
                
            # Detect codex response sections
            if stripped == "codex":
                in_codex_response = True
                result_parts = []  # Reset - take the last codex block
                continue
            
            # Stop at "tokens used"
            if stripped == "tokens used":
                break
                
            if in_codex_response:
                result_parts.append(line)
        
        return '\n'.join(result_parts).strip()
    
    def _split_message(self, text, max_len=4000):
        """Split a long message into chunks for Telegram."""
        if len(text) <= max_len:
            return [text]
        
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            # Try to split at a newline
            split_pos = text.rfind('\n', 0, max_len)
            if split_pos == -1:
                split_pos = max_len
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip('\n')
        
        return chunks
    
    def stop(self):
        """Stop any running subprocess."""
        self.running = False
        with self.lock:
            if self.current_process:
                try:
                    self.current_process.kill()
                    self.current_process.wait(timeout=2)
                except:
                    pass
                self.current_process = None
        logger.info("CLIBridge stopped.")
