import asyncio
import subprocess
import difflib
import json
import sys
import os
from pathlib import Path
from contextlib import asynccontextmanager
from typing import List, Optional, Callable, Dict, Any, Tuple
from functools import partial

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
import uvicorn

# --- Configuration & Constants ---
PROMPT_FILE = Path("refactor_prompt.txt")
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
    <head>
        <title>自動リファクタリングエージェント</title>
        <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/diff2html/bundles/css/diff2html.min.css" />
        <script type="text/javascript" src="https://cdn.jsdelivr.net/npm/diff2html/bundles/js/diff2html-ui.min.js"></script>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; margin: 0; background-color: #f0f2f5; color: #333; }
            #header { background-color: #fff; padding: 15px 20px; border-bottom: 1px solid #ddd; box-shadow: 0 2px 4px rgba(0,0,0,0.05 ); display: flex; align-items: center; justify-content: space-between; }
            h1 { margin: 0; font-size: 1.5em; }
            #status-indicator { display: flex; align-items: center; gap: 8px; font-weight: 500; }
            .dot { height: 12px; width: 12px; background-color: #bbb; border-radius: 50%; display: inline-block; transition: background-color 0.3s; }
            .dot.connected { background-color: #28a745; }
            .dot.disconnected { background-color: #dc3545; }
            #content { padding: 20px; }
            .log-entry { background-color: #fff; border: 1px solid #e1e4e8; border-radius: 6px; margin-bottom: 15px; overflow: hidden; }
            .log-header { padding: 10px 15px; background-color: #f6f8fa; border-bottom: 1px solid #e1e4e8; font-weight: 600; }
            .log-body { padding: 15px; }
            .status-message { font-style: italic; color: #586069; }
        </style>
    </head>
    <body>
        <div id="header">
            <h1>自動リファクタリングエージェント</h1>
            <div id="status-indicator">
                <span id="status-text">接続中...</span>
                <div id="status-dot" class="dot"></div>
            </div>
        </div>
        <div id="content">
            <div id="logs">
                <div class="log-entry"><div class="log-body status-message">監視対象ディレクトリ内の.pyファイルを変更・保存すると、ここに結果が表示されます。</div></div>
            </div>
        </div>
        <script>
            const logsContainer = document.getElementById('logs');
            const statusText = document.getElementById('status-text');
            const statusDot = document.getElementById('status-dot');

            const ws = new WebSocket(`ws://localhost:8000/ws`);

            ws.onopen = function(event) {
                console.log("WebSocket connection established.");
                statusText.textContent = "接続済み";
                statusDot.className = 'dot connected';
            };

            ws.onclose = function(event) {
                console.log("WebSocket connection closed.");
                statusText.textContent = "未接続";
                statusDot.className = 'dot disconnected';
            };

            ws.onerror = function(event) {
                console.error("WebSocket error:", event);
                statusText.textContent = "エラー";
                statusDot.className = 'dot disconnected';
            };

            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                let logEntry;
                if (data.id) {
                    logEntry = document.getElementById(data.id);
                }
                if (!logEntry) {
                    logEntry = document.createElement('div');
                    logEntry.className = 'log-entry';
                    if (data.id) {
                        logEntry.id = data.id;
                    }
                    const header = document.createElement('div');
                    header.className = 'log-header';
                    header.textContent = data.filename || `ステータス更新 (${new Date().toLocaleTimeString()})`;
                    const body = document.createElement('div');
                    body.className = 'log-body';
                    logEntry.appendChild(header);
                    logEntry.appendChild(body);
                    logsContainer.prepend(logEntry);
                }
                const logBody = logEntry.querySelector('.log-body');
                if (data.type === 'status') {
                    logBody.innerHTML = `<div class="status-message">${data.message}</div>`;
                } else if (data.type === 'diff') {
                    logBody.innerHTML = '';
                    const diff2htmlUi = new Diff2HtmlUI(logBody, data.diff, {
                        drawFileList: false,
                        matching: 'lines',
                        outputFormat: 'side-by-side'
                    });
                    diff2htmlUi.draw();
                }
            };
        </script>
    </body>
</html>
"""

# --- Pure Domain Functions ---

def is_target_file(file_path: Path) -> bool:
    """リファクタリング対象のファイルかどうかを判定する純粋関数"""
    return (
        file_path.suffix == '.py' and 
        'agent_server.py' not in file_path.name
    )

def generate_task_id(filename: str, mtime: float) -> str:
    """一意のタスクIDを生成する純粋関数"""
    return f"task-{filename}-{mtime}"

def create_payload(task_id: str, msg_type: str, filename: str, content_key: str, content_value: str) -> str:
    """WebSocket用のJSONペイロードを生成する純粋関数"""
    return json.dumps({
        'id': task_id,
        'type': msg_type,
        'filename': filename,
        content_key: content_value
    })

def format_error_html(error_message: str) -> str:
    """エラーメッセージをHTML形式に整形する純粋関数"""
    return (
        f"<strong style='color: red;'>エラーが発生しました:</strong>"
        f"<pre style='white-space: pre-wrap; background-color: #fbebeb; padding: 10px; border-radius: 4px;'>"
        f"{error_message}</pre>"
    )

def calculate_diff(original: str, refactored: str, filename: str) -> str:
    """2つの文字列の差分を生成する純粋関数"""
    diff_lines = difflib.unified_diff(
        original.splitlines(keepends=True),
        refactored.splitlines(keepends=True),
        fromfile=f'a/{filename}',
        tofile=f'b/{filename} (refactored)'
    )
    return "".join(diff_lines)

def get_gemini_command() -> List[str]:
    """実行すべきGeminiコマンドのリストを返す純粋関数"""
    gemini_cli_path = Path.home() / "/usr/local/bin/gemini"
    return [str(gemini_cli_path)] if gemini_cli_path.exists() else ['gemini']

# --- Side Effects & I/O Wrappers ---

def read_text_file(path: Path) -> str:
    """ファイル読み込みを行う副作用関数"""
    return path.read_text(encoding="utf-8")

def run_subprocess(command: List[str], input_text: str) -> str:
    """サブプロセスを実行する副作用関数"""
    result = subprocess.run(
        command,
        input=input_text,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8"
    )
    return result.stdout

# --- Logic Composition ---

def execute_refactor_logic(prompt_path: Path, target_file_path: Path) -> str:
    """リファクタリングの実行ロジックを構成する関数"""
    try:
        prompt = read_text_file(prompt_path)
        original_code = read_text_file(target_file_path)
        input_data = f"{prompt}\n---\n{original_code}"
        command = get_gemini_command()
        
        return run_subprocess(command, input_data)
        
    except FileNotFoundError:
        return f"エラー: コマンドまたはファイルが見つかりません。"
    except subprocess.CalledProcessError as e:
        return f"リファクタリングコマンドの実行に失敗しました: {e.stderr or e.stdout}"
    except Exception as e:
        return f"予期せぬエラーが発生しました: {e}"

# --- Async & State Management ---

class ConnectionManager:
    """WebSocket接続を管理するクラス（状態保持のため必要）"""
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        if not self.active_connections:
            return
        # 関数型アプローチ: 接続ごとの送信タスクを作成し、並行実行する
        await asyncio.gather(
            *(connection.send_text(message) for connection in self.active_connections)
        )

manager = ConnectionManager()

async def process_refactoring_pipeline(
    file_path: Path, 
    manager: ConnectionManager,
    prompt_path: Path = PROMPT_FILE
) -> None:
    """リファクタリングのパイプライン処理を実行する非同期関数"""
    filename = file_path.name
    try:
        mtime = os.path.getmtime(file_path)
    except FileNotFoundError:
        return 

    task_id = generate_task_id(filename, mtime)

    # ステータス通知ヘルパー
    async def notify(msg: str):
        payload = create_payload(task_id, 'status', filename, 'message', msg)
        await manager.broadcast(payload)

    print(f"変更を検知: {filename}")
    await notify(f"変更を検知: '{filename}'。処理を開始します...")

    # リファクタリング実行
    await notify("Geminiに関数型リファクタリングを依頼中... (これには十数秒かかることがあります)")
    
    # ブロッキングIOをスレッドプールで実行
    refactored_code = await asyncio.to_thread(
        execute_refactor_logic, prompt_path, file_path
    )

    if "エラー" in refactored_code or "失敗しました" in refactored_code:
        error_html = format_error_html(refactored_code)
        await notify(error_html)
        print(f"エラー情報をWeb UIに送信しました: {filename}")
    else:
        await notify("差分を生成中...")
        original_code = await asyncio.to_thread(read_text_file, file_path)
        diff_text = calculate_diff(original_code, refactored_code, filename)
        
        diff_payload = create_payload(task_id, 'diff', filename, 'diff', diff_text)
        await manager.broadcast(diff_payload)
        print(f"差分情報をWeb UIに送信しました: {filename}")

class RefactorEventHandler(FileSystemEventHandler):
    """ファイルシステムイベントをハンドリングし、非同期処理へブリッジするクラス"""
    def __init__(self, loop: asyncio.AbstractEventLoop, manager: ConnectionManager):
        self.loop = loop
        self.manager = manager

    def on_modified(self, event: FileSystemEvent):
        if event.is_directory:
            return

        file_path = Path(str(event.src_path))
        
        if is_target_file(file_path):
            # 非同期パイプラインをスレッドセーフにスケジュール
            asyncio.run_coroutine_threadsafe(
                process_refactoring_pipeline(file_path, self.manager), 
                self.loop
            )

# --- FastAPI Setup ---

@asynccontextmanager
async def lifespan(app_instance: FastAPI):
    watch_path = sys.argv[1] if len(sys.argv) > 1 else '.'
    
    loop = asyncio.get_running_loop()
    event_handler = RefactorEventHandler(loop, manager)
    
    observer = Observer()
    observer.schedule(event_handler, watch_path, recursive=True)
    observer.start()
    
    print(f"ファイル監視を開始しました: {Path(watch_path).resolve()}")
    
    yield
    
    observer.stop()
    observer.join()
    print("ファイル監視を停止しました。")

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def get():
    return HTMLResponse(HTML_TEMPLATE)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    print("WebSocket connection open")
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("WebSocket connection closed")

if __name__ == "__main__":
    watch_directory = sys.argv[1] if len(sys.argv) > 1 else '.'
    print("--- 自動リファクタリングエージェント サーバー ---")
    print(f"監視対象ディレクトリ: {Path(watch_directory).resolve()}")
    print("ブラウザで http://localhost:8000 を開いてください 。")
    print("---------------------------------------------")
    uvicorn.run(app, host="0.0.0.0", port=8000)
