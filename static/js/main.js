const logsContainer = document.getElementById('logs');
const statusText = document.getElementById('status-text');
const statusDot = document.getElementById('status-dot');

const ws = new WebSocket(`ws://${window.location.host}/ws`);

ws.onopen = function(event) { statusText.textContent = "接続済み"; statusDot.className = 'dot connected'; };
ws.onclose = function(event) { statusText.textContent = "未接続"; statusDot.className = 'dot disconnected'; };
ws.onerror = function(event) { statusText.textContent = "エラー"; statusDot.className = 'dot disconnected'; };

// コピー処理を行う関数
function copyToClipboard(text, buttonElement) {
    const originalText = buttonElement.textContent;

    // 成功時のUI更新
    const onCopySuccess = () => {
        buttonElement.textContent = 'コピーしました！';
        buttonElement.classList.add('copied');
        setTimeout(() => {
            buttonElement.textContent = originalText;
            buttonElement.classList.remove('copied');
        }, 2000);
    };

    // 失敗時のUI更新
    const onCopyError = (err) => {
        console.error('コピー失敗:', err);
        buttonElement.textContent = '手動でコピーしてください';
        // 手動コピー用のテキストエリアを表示
        showManualCopyDialog(text);
        setTimeout(() => {
            buttonElement.textContent = originalText;
        }, 3000);
    };

    // 1. Clipboard API (モダンブラウザ/HTTPS/localhost)
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text)
            .then(onCopySuccess)
            .catch((err) => {
                // APIはあるが権限などで拒否された場合はレガシーへ
                console.warn('Clipboard API failed, trying execCommand...', err);
                fallbackCopyTextToClipboard(text, onCopySuccess, onCopyError);
            });
    } else {
        // 2. execCommand (レガシー/非セキュア環境)
        fallbackCopyTextToClipboard(text, onCopySuccess, onCopyError);
    }
}

// レガシーなコピー処理 (execCommand)
function fallbackCopyTextToClipboard(text, onSuccess, onError) {
    try {
        const textArea = document.createElement("textarea");
        textArea.value = text;
        
        // 画面外に配置せず、固定配置で見えないようにする（iOSなどで選択可能にするため）
        textArea.style.position = "fixed";
        textArea.style.left = "-9999px";
        textArea.style.top = "0";
        
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        
        const successful = document.execCommand('copy');
        document.body.removeChild(textArea);
        
        if (successful) {
            onSuccess();
        } else {
            throw new Error('execCommand returned false');
        }
    } catch (err) {
        onError(err);
    }
}

// 手動コピー用のダイアログを表示
function showManualCopyDialog(text) {
    // 既存のダイアログがあれば削除
    const existing = document.getElementById('manual-copy-dialog');
    if (existing) existing.remove();

    const dialog = document.createElement('div');
    dialog.id = 'manual-copy-dialog';
    dialog.style.cssText = `
        position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
        background: white; border: 1px solid #ccc; padding: 20px; z-index: 1000;
        box-shadow: 0 4px 12px rgba(0,0,0,0.15); border-radius: 8px; width: 80%; max-width: 600px;
    `;
    
    const title = document.createElement('h3');
    title.textContent = '以下のテキストをコピーしてください (Ctrl+C)';
    title.style.marginTop = '0';
    
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.cssText = 'width: 100%; height: 200px; margin: 10px 0; padding: 8px; box-sizing: border-box;';
    textarea.readOnly = true;

    const closeBtn = document.createElement('button');
    closeBtn.textContent = '閉じる';
    closeBtn.style.cssText = 'padding: 8px 16px; background: #f0f2f5; border: 1px solid #ccc; border-radius: 4px; cursor: pointer;';
    closeBtn.onclick = () => dialog.remove();

    dialog.appendChild(title);
    dialog.appendChild(textarea);
    dialog.appendChild(closeBtn);
    document.body.appendChild(dialog);

    textarea.focus();
    textarea.select();
}


ws.onmessage = function(event) {
    const data = JSON.parse(event.data);
    let logEntry = document.getElementById(data.id);

    if (!logEntry) {
        logEntry = document.createElement('div');
        logEntry.className = 'log-entry';
        logEntry.id = data.id;
        logEntry.innerHTML = `<div class="log-header"><span>${data.filename}</span></div><div class="log-body"></div>`;
        logsContainer.prepend(logEntry);
    }
    
    const logHeader = logEntry.querySelector('.log-header');
    const logBody = logEntry.querySelector('.log-body');

    if (data.type === 'error') {
        logEntry.classList.add('error-entry');
        logBody.innerHTML = `<div class="error-message">${data.error}</div>`;
    } else if (data.type === 'status') {
        logBody.innerHTML = `<div class="status-message">${data.message}</div>`;
    } else if (data.type === 'diff') {
        logBody.innerHTML = '';
        new Diff2HtmlUI(logBody, data.diff, { drawFileList: false, matching: 'lines', outputFormat: 'side-by-side' }).draw();
        
        /* コピーボタン機能 */
        const existingButton = logHeader.querySelector('.copy-button');
        if (existingButton) existingButton.remove();
        
        const copyButton = document.createElement('button');
        copyButton.textContent = 'リファクタ後コードをコピー';
        copyButton.className = 'copy-button';
        
        copyButton.onclick = function() {
            if (!data.refactored_code) {
                alert("コピーするコードが見つかりませんでした。");
                return;
            }
            copyToClipboard(data.refactored_code, copyButton);
        };
        
        logHeader.appendChild(copyButton);
    }
};