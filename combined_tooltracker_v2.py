
import time
import json
import random
from collections import defaultdict


class ToolCallTracker:
    def __init__(self, max_tokens=50000, warning_threshold=0.8, hard_threshold=0.9):
        self.max_tokens = max_tokens
        self.warning_threshold = warning_threshold
        self.hard_threshold = hard_threshold
        self.tool_calls = defaultdict(list)
        self.token_usage = 0
        self.start_time = time.time()
        self.fallbacks = {}
        self.validation_log = []
        self.register_fallback("rate_limit", lambda: "Rate limit hit. Retrying with fallback...")
        self.register_fallback("token_limit", lambda: "Token limit reached. Starting new chat.")

    def register_fallback(self, name, fallback_func):
        self.fallbacks[name] = fallback_func

    def call_tool(self, tool_name, action_func, metadata=None):
        if metadata is None:
            metadata = {}

        if self.token_usage >= self.hard_threshold * self.max_tokens:
            self._enforce_hard_token_limit()
            return self.fallbacks.get("token_limit", lambda: "Token limit reached. Please start a new chat.")()

        last_call_time = self.tool_calls[tool_name][-1]["timestamp"] if self.tool_calls[tool_name] else 0
        time_since_last_call = time.time() - last_call_time
        if tool_name == "web_search" and len(self.tool_calls[tool_name]) >= 10 and time_since_last_call < 6:
            return self.fallbacks.get("rate_limit", lambda: "{0} rate limit hit. Retrying...".format(tool_name))()

        try:
            result = retry_with_backoff(action_func, max_retries=3)
            if result is None:
                fallback = self.fallbacks.get(tool_name, None)
                if fallback:
                    return fallback()
                else:
                    raise Exception("All retries and fallbacks failed")

            call_duration = time.time() - (self.tool_calls[tool_name][-1]["timestamp"] if self.tool_calls[tool_name] else time.time())
            call_tokens = 100 + int(call_duration * 10)
            self.token_usage += call_tokens

            call_log = {
                "tool": tool_name,
                "timestamp": time.time(),
                "tokens_used": call_tokens,
                "metadata": metadata,
                "status": "success",
                "result": str(result)[:100] + "..."
            }
            self.tool_calls[tool_name].append(call_log)
            self.validation_log.append(call_log)

            if self.token_usage >= self.warning_threshold * self.max_tokens:
                self._trigger_context_transfer_warning()

            return result

        except Exception as e:
            error_log = {
                "tool": tool_name,
                "timestamp": time.time(),
                "error": str(e),
                "metadata": metadata,
                "status": "failed"
            }
            self.tool_calls[tool_name].append(error_log)
            self.validation_log.append(error_log)
            raise

    def _enforce_hard_token_limit(self):
        summary = self._summarize_context()
        print("HARD TOKEN LIMIT REACHED ({0}/{1}). Starting new chat with summary:".format(self.token_usage, self.max_tokens))
        print(summary)
        self.token_usage = 0
        self.tool_calls = defaultdict(list)

    def _trigger_context_transfer_warning(self):
        print("TOKEN WARNING: {0}/{1} tokens used (80 percent limit). Consider starting a new chat soon.".format(self.token_usage, self.max_tokens))

    def _summarize_context(self):
        summary = {
            "decisions_made": [],
            "validated_claims": [],
            "resource_limits_encountered": [],
            "pending_actions": []
        }
        for log in self.validation_log:
            if log["status"] == "success" and "claim" in log.get("metadata", {}):
                summary["validated_claims"].append(log["metadata"]["claim"])
            if "error" in log:
                summary["resource_limits_encountered"].append("{0}: {1}".format(log['tool'], log['error']))
        return json.dumps(summary, indent=2)

    def get_token_usage(self):
        percentage = (self.token_usage / self.max_tokens) * 100
        return {
            "tokens_used": self.token_usage,
            "max_tokens": self.max_tokens,
            "percentage": round(percentage, 2)
        }

    def get_validation_log(self):
        return self.validation_log


def retry_with_backoff(action_func, max_retries=3, initial_delay=2, backoff_factor=2, max_delay=10):
    last_exception = None
    for attempt in range(max_retries):
        try:
            return action_func()
        except Exception as e:
            last_exception = e
            if attempt < max_retries - 1:
                delay = min(initial_delay * (backoff_factor ** attempt), max_delay)
                jitter = random.uniform(0, delay * 0.1)
                actual_delay = delay + jitter
                print("Attempt {0} failed. Retrying in {1:.2f} seconds...".format(attempt + 1, actual_delay))
                time.sleep(actual_delay)
            else:
                print("All {0} attempts failed. Last error: {1}".format(max_retries, e))
    return None


def get_export_method(user_message):
    user_message = user_message.lower()
    devtools_keywords = [
        "devtools", "dev tools", "developer tools", "browser",
        "json", "structured", "data", "full data", "machine-readable"
    ]
    singlefile_keywords = [
        "singlefile", "single file", "html", "archive", "offline",
        "readable", "formatting", "preserve", "save page", "download page"
    ]
    if any(keyword in user_message for keyword in devtools_keywords):
        return "devtools"
    elif any(keyword in user_message for keyword in singlefile_keywords):
        return "singlefile"
    else:
        return "both"


def handle_chat_export(user_message):
    method = get_export_method(user_message)
    validation_log_entry = {
        "protocol": 12,
        "user_request": user_message,
        "method_detected": method,
        "timestamp": time.time()
    }
    if 'validation_log' in globals():
        validation_log.append(validation_log_entry)
    
    if method == "devtools":
        return "DevTools Method: Open DevTools (F12), go to Network tab, filter for chat, find request, copy response, save as JSON."
    elif method == "singlefile":
        return "SingleFile Method: Install SingleFile extension, click icon, save as HTML."
    else:
        return "Export Options: Use DevTools for JSON or SingleFile for HTML. See Context Rules v8.12 for details."


def handle_backend_error(user_request, max_retries=3):
    def action():
        raise Exception("Backend generation error")
    result = retry_with_backoff(action, max_retries=max_retries)
    if result is None:
        return "Backend Error Detected. Please retry, simplify, wait, or report."
    return result


# Initialize ToolCallTracker and register functions
try:
    tracker = ToolCallTracker(max_tokens=50000)
    vibe = type('Vibe', (), {
        'context': {
            "tool_call_tracker": tracker,
            "retry_with_backoff": retry_with_backoff,
            "get_export_method": get_export_method,
            "handle_chat_export": handle_chat_export,
            "handle_backend_error": handle_backend_error
        }
    })()
    print("Combined script initialized successfully.")
except Exception as e:
    print("Failed to initialize combined script: {0}".format(e))

if 'validation_log' not in globals():
    validation_log = []
