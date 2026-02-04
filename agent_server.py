import asyncio
import difflib
import json
import subprocess
import sys
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileSystemEvent
import uvicorn

# --- 定数・設定 (Configuration) ---
PROMPT_FILE = Path("refactor_prompt.txt")

# --- 純粋関数 (Pure Functions) ---
def is_watchable_file(event: FileSystemEvent) -> bool:
    path = str(event.src_path)
    return not event.is_directory and path.endswith('.py') and 'agent_server.py' not in path

def generate_task_id(file_path: Path) -> str:
    return f"task-{file_path.name}-{file_path.stat().st_mtime}"

def construct_gemini_input(prompt: str, code: str) -> str:
    return f"{prompt}\n---\n{code}"

def determine_gemini_command() -> List[str]:
    gemini_cli_path = Path.home() / "/usr/local/bin/gemini"
    return [str(gemini_cli_path)] if gemini_cli_path.exists() else ['gemini']

def generate_diff(original: str, refactored: str, filename: str) -> str:
    diff_lines = difflib.unified_diff(
        original.splitlines(keepends=True),
        refactored.splitlines(keepends=True),
        fromfile=f'a/{filename}',
        tofile=f'b/{filename} (refactored)'
    )
    return "".join(diff_lines)

def create_message_payload(task_id: str, filename: str, msg_type: str, data: Dict[str, Any]) -> str:
    """WebSocket用のJSONメッセージを作成する"""
    payload = {'id': task_id, 'type': msg_type, 'filename': filename, **data}
    return json.dumps(payload)

# --- 副作用ラッパー (I/O) ---
class SubprocessResult:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0, error: Exception = None):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode
        self.error = error
    def is_successful(self) -> bool:
        return self.returncode == 0 and self.error is None

def execute_refactor_subprocess(command: List[str], input_data: str) -> SubprocessResult:
    try:
        result = subprocess.run(
            command, input=input_data, capture_output=True, text=True,
            check=True, encoding="utf-8"
        )
        return SubprocessResult(stdout=result.stdout, stderr=result.stderr, returncode=result.returncode)
    except FileNotFoundError as e:
        return SubprocessResult(error=e, stderr=f"コマンド '{command[0]}' が見つかりません。")
    except subprocess.CalledProcessError as e:
        return SubprocessResult(error=e, stdout=e.stdout, stderr=e.stderr, returncode=e.returncode)
    except Exception as e:
        return SubprocessResult(error=e, stderr=f"予期せぬサブプロセスエラーが発生しました: {e}")

def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")

# --- アプリケーションロジック (Composed) ---
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []
    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
    async def broadcast(self, message: str):
        if self.active_connections:
            await asyncio.gather(*(conn.send_text(message) for conn in self.active_connections))

manager = ConnectionManager()

async def pipeline_refactor(file_path: Path, task_id: str):
    """リファクタリングの一連の処理フローを実行する"""
    filename = file_path.name
    try:
        await manager.broadcast(create_message_payload(task_id, filename, 'status', {'message': f"変更を検知: '{filename}'。処理を開始します..."}))

        prompt = read_text_file(PROMPT_FILE)
        original_code = read_text_file(file_path)
        input_data = construct_gemini_input(prompt, original_code)
        command = determine_gemini_command()

        await manager.broadcast(create_message_payload(task_id, filename, 'status', {'message': "Geminiに関数型リファクタリングを依頼中..."}))
        
        result = await asyncio.to_thread(execute_refactor_subprocess, command, input_data)

        if not result.is_successful():
            error_message = result.stderr or str(result.error)
            await manager.broadcast(create_message_payload(task_id, filename, 'error', {'error': error_message}))
            print(f"エラー情報をWeb UIに送信しました: {filename}")
            return

        refactored_code = result.stdout
        await manager.broadcast(create_message_payload(task_id, filename, 'status', {'message': "差分を生成中..."}))

        diff_text = generate_diff(original_code, refactored_code, filename)

        await manager.broadcast(
            create_message_payload(
                task_id,
                filename,
                'diff',
                {'diff': diff_text, 'refactored_code': refactored_code}
            )
        )
        print(f"差分情報をWeb UIに送信しました: {filename}")

    except Exception as e:
        error_message = f"サーバー内部で予期せぬエラーが発生しました: {type(e).__name__}: {e}"
        await manager.broadcast(create_message_payload(task_id, filename, 'error', {'error': error_message}))
        print(error_message)

class RefactorEventHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self.loop = loop
    def on_modified(self, event: FileSystemEvent):
        if not is_watchable_file(event): return
        file_path = Path(event.src_path)
        task_id = generate_task_id(file_path)
        print(f"変更を検知: {file_path.name}")
        asyncio.run_coroutine_threadsafe(pipeline_refactor(file_path, task_id), self.loop)

@asynccontextmanager
async def lifespan(app: FastAPI):
    watch_path = sys.argv[1] if len(sys.argv) > 1 else '.'
    app.state.watch_path = watch_path
    loop = asyncio.get_running_loop()
    event_handler = RefactorEventHandler(loop)
    observer = Observer()
    observer.schedule(event_handler, watch_path, recursive=True)
    observer.start()
    print(f"ファイル監視を開始しました: {Path(watch_path).resolve()}")
    app.state.observer = observer
    yield
    observer.stop()
    observer.join()
    print("ファイル監視を停止しました。")

app = FastAPI(lifespan=lifespan)

# 静的ファイルをマウント
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def get_root():
    # テンプレートファイルを読み込んで返す
    return HTMLResponse(read_text_file(Path("templates/index.html")))

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    print("WebSocket connection open")
    try:
        while True: await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        print("WebSocket connection closed")

if __name__ == "__main__":
    watch_directory = sys.argv[1] if len(sys.argv) > 1 else '.'
    print("--- 自動リファクタリングエージェント サーバー ---")
    print(f"監視対象ディレクトリ: {Path(watch_directory).resolve()}")
    print("ブラウザで http://localhost:8000 を開いてください  。")
    print("---------------------------------------------")
    uvicorn.run(app, host="0.0.0.0", port=8000)