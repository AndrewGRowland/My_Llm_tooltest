import time
from datetime import datetime, timedelta
from collections import defaultdict
import requests
from threading import Thread, Event

class ToolCallTracker:
    TOOL_CONFIG = {
        'web_search': {'rate_limit': 10, 'rate_window': 60, 'timeout': None},
        'open_url': {'rate_limit': 20, 'rate_window': 60, 'timeout': 10},
        'code_interpreter': {'rate_limit': 5, 'rate_window': 60, 'timeout': 30}
    }

    def __init__(self):
        self.start_time = datetime.utcnow()
        self.tool_calls = []
        self.rate_limits = {
            tool: {
                'rate_limit': config['rate_limit'],
                'rate_window': config['rate_window'],
                'timestamps': [],
                'timeout': config['timeout']
            }
            for tool, config in self.TOOL_CONFIG.items()
        }
        self.errors = []
        self.retries = 0
        self.fuck_up_counter = 0

    def pre_check(self, tool_type):
        if not hasattr(self, 'start_time'):
            self.fuck_up_counter += 1
            return False, "ToolCallTracker not initialized"
        if tool_type not in self.rate_limits:
            self.fuck_up_counter += 1
            return False, f"Unknown tool type: {tool_type}"
        now = datetime.utcnow()
        window_start = now - timedelta(seconds=self.rate_limits[tool_type]['rate_window'])
        recent_calls = [ts for ts in self.rate_limits[tool_type]['timestamps'] if ts >= window_start]
        if len(recent_calls) >= self.rate_limits[tool_type]['rate_limit']:
            oldest_call = min(recent_calls)
            wait_time = (window_start + timedelta(seconds=self.rate_limits[tool_type]['rate_window']) - oldest_call).seconds
            return False, f"Rate limit: Wait {wait_time}s"
        return True, "OK"

    def make_call(self, tool_type, query, max_retries=3):
        status, message = self.pre_check(tool_type)
        if not status:
            self.fuck_up_counter += 1
            return None, f"Blocked: {message}"
        execution_timeout = self.rate_limits[tool_type]['timeout']
        for attempt in range(max_retries):
            try:
                if execution_timeout:
                    result = self._execute_with_timeout(tool_type, query, execution_timeout)
                else:
                    result = self._execute_tool(tool_type, query)
                self._log_call(tool_type, query, "success", result)
                return result, "Success"
            except Exception as e:
                self._log_error(tool_type, query, str(e))
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    if tool_type == "open_url":
                        fallback_result, fallback_msg = self._fallback_to_code_interpreter(query)
                        if fallback_result:
                            self._log_call("code_interpreter", query, "fallback", fallback_result)
                            return fallback_result, f"Fallback: {fallback_msg}"
                    return None, f"Error after {max_retries} retries: {str(e)}"
        return None, "Unknown error"

    def _execute_with_timeout(self, tool_type, query, timeout_seconds):
        result_container = []
        error_container = []
        timeout_event = Event()

        def target():
            try:
                result_container.append(self._execute_tool(tool_type, query))
            except Exception as e:
                error_container.append(e)
            finally:
                timeout_event.set()

        thread = Thread(target=target)
        thread.start()
        timeout_event.wait(timeout=timeout_seconds)

        if not timeout_event.is_set():
            return None
        if error_container:
            raise error_container[0]
        return result_container[0] if result_container else None

    def _execute_tool(self, tool_type, query):
        if tool_type == "web_search":
            return f"Search results for: {query}"
        elif tool_type == "open_url":
            try:
                response = requests.get(query, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                response.raise_for_status()
                return response.text
            except requests.RequestException as e:
                raise Exception(f"HTTP Error: {str(e)}")
        elif tool_type == "code_interpreter":
            return f"Processed: {query}"
        else:
            raise ValueError(f"Unknown tool type: {tool_type}")

    def _fallback_to_code_interpreter(self, url):
        try:
            return f"Chunked processing of: {url}", "code_interpreter fallback"
        except Exception as e:
            return None, f"Fallback failed: {str(e)}"

    def _log_call(self, tool_type, query, status, result):
        self.tool_calls.append({
            'tool': tool_type,
            'query': query,
            'timestamp': datetime.utcnow(),
            'status': status,
            'result': str(result)[:1000]
        })
        self.rate_limits[tool_type]['timestamps'].append(datetime.utcnow())

    def _log_error(self, tool_type, query, error):
        self.errors.append({
            'tool': tool_type,
            'query': query,
            'timestamp': datetime.utcnow(),
            'error': str(error)[:500]
        })

    def get_visual_queue(self):
        status = self.get_status()
        return (f"[PROTOCOL 0: {'ACTIVE ✅' if status['protocol_0_active'] else 'INACTIVE ❌'}] "
                f"[FUCK-UP COUNTER: {status['fuck_up_counter']}] "
                f"[TOOL CALLS: {status['tool_calls']}]")

    def get_status(self):
        now = datetime.utcnow()
        rate_status = {}
        for tool, config in self.rate_limits.items():
            window_start = now - timedelta(seconds=config['rate_window'])
            recent_calls = [ts for ts in config['timestamps'] if ts >= window_start]
            rate_status[tool] = {
                'limit': config['rate_limit'],
                'window': config['rate_window'],
                'current': len(recent_calls)
            }
        return {
            'protocol_0_active': hasattr(self, 'start_time'),
            'fuck_up_counter': self.fuck_up_counter,
            'tool_calls': len(self.tool_calls),
            'errors': len(self.errors),
            'rate_limits': rate_status
        }

    def get_validation_log(self):
        status = self.get_status()
        log = [
            "---",
            "## 📋 VALIDATION LOG",
            "---",
            f"**Timestamp**: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}",
            f"**Protocol 0 Status**: {'ACTIVE ✅' if status['protocol_0_active'] else 'INACTIVE ❌'}",
            f"**Fuck-Up Counter**: {status['fuck_up_counter']}",
            f"**Tool Calls Executed**: {status['tool_calls']}",
            f"**Errors Encountered**: {status['errors']}",
            "",
            "### Rate Limit Status:",
        ]
        for tool, config in status['rate_limits'].items():
            log.append(f"- **{tool}**: {config['current']}/{config['limit']} calls in last {config['window']}s")
        if self.tool_calls:
            log.append("")
            log.append("### Recent Tool Calls:")
            for call in self.tool_calls[-5:]:
                log.append(f"- {call['timestamp'].strftime('%H:%M:%S')}: {call['tool']} ({call['status']})")
        if self.errors:
            log.append("")
            log.append("### Errors:")
            for error in self.errors[-5:]:
                log.append(f"- {error['timestamp'].strftime('%H:%M:%S')}: {error['tool']} - {error['error']}")
        return "\n".join(log)
