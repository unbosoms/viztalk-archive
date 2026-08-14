#!/usr/bin/env python3
"""HTTP Range (206 Partial Content) 対応の簡易サーバー。
mockup ディレクトリで実行して、音声ファイルの seek を可能にする。

使い方: python3 serve.py [PORT]  (デフォ 8000)
"""
import http.server
import os
import re
import sys
import mimetypes


class RangeRequestHandler(http.server.SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler に Range 対応を追加。"""

    def send_head(self):
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        if not os.path.isfile(path):
            self.send_error(404, "File not found")
            return None
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404, "File not found")
            return None

        fs = os.fstat(f.fileno())
        size = fs.st_size
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        range_header = self.headers.get("Range")

        if range_header:
            m = re.match(r"bytes=(\d*)-(\d*)", range_header)
            if not m:
                self.send_error(400, "Invalid Range")
                f.close(); return None
            start = int(m.group(1)) if m.group(1) else 0
            end = int(m.group(2)) if m.group(2) else size - 1
            if start >= size or end >= size or start > end:
                self.send_error(416, "Requested Range Not Satisfiable")
                f.close(); return None
            self.send_response(206)
            self.send_header("Content-Type", ctype)
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.send_header("Content-Length", str(end - start + 1))
            self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
            self.end_headers()
            f.seek(start)
            self._range_end = end
            self._range_start = start
            return f

        # Full response
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(size))
        self.send_header("Last-Modified", self.date_time_string(fs.st_mtime))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        """Range response の場合、指定範囲だけコピー。
        ブラウザが seek/navigate で接続を切ると BrokenPipe になるので握りつぶす。"""
        try:
            if hasattr(self, "_range_end"):
                remaining = self._range_end - self._range_start + 1
                while remaining > 0:
                    chunk = source.read(min(64 * 1024, remaining))
                    if not chunk: break
                    outputfile.write(chunk)
                    remaining -= len(chunk)
                del self._range_end, self._range_start
            else:
                super().copyfile(source, outputfile)
        except (BrokenPipeError, ConnectionResetError):
            # クライアントが切断（seek/navigate）→ 正常挙動なので黙って終了
            pass

    def log_message(self, format, *args):
        """アクセスログはそのまま出す。ただしBrokenPipe警告は抑制済み。"""
        super().log_message(format, *args)

    def handle_one_request(self):
        """接続切断エラーを静かに扱う。"""
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "mockup"))
    server = http.server.ThreadingHTTPServer(("", port), RangeRequestHandler)
    print(f"Serving mockup/ at http://localhost:{port}/  (HTTP Range 対応)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
