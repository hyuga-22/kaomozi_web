// ==========================================================
// クリップボードへのコピー（共通関数）
//
// navigator.clipboard.writeText() は「セキュアな文脈」
// （HTTPS、または localhost）でしか使えない。
// IPアドレス＋HTTPでのアクセス（例: http://192.168.x.x:5000）など
// 非セキュアな文脈では navigator.clipboard 自体が存在しないため、
// 古い document.execCommand("copy") にフォールバックする。
// ==========================================================
function copyToClipboard(text) {
    if (navigator.clipboard && window.isSecureContext) {
        return navigator.clipboard.writeText(text);
    }

    return new Promise((resolve, reject) => {
        const textarea = document.createElement("textarea");
        textarea.value = text;
        // 画面には表示せず、スクロール位置もずらさない
        textarea.style.position = "fixed";
        textarea.style.top = "0";
        textarea.style.left = "0";
        textarea.style.opacity = "0";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();

        try {
            const ok = document.execCommand("copy");
            document.body.removeChild(textarea);
            if (ok) {
                resolve();
            } else {
                reject(new Error("execCommand('copy') に失敗しました"));
            }
        } catch (err) {
            document.body.removeChild(textarea);
            reject(err);
        }
    });
}
