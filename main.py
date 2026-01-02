import flet as ft
import os
import threading
import time
import queue
import tempfile
import shutil
import sys
import traceback
import re
import unicodedata
from datetime import datetime

# --- CẤU HÌNH ---
VERSION = "v8.1 Enterprise (Final Stable)"
COLOR_PRIMARY = "#d32f2f"
COLOR_BG = "#121212"
HISTORY_KEY = "hust_history_v1"
SETTINGS_KEY = "hust_settings_v1"

# --- HELPER FUNCTIONS ---

def safe_put(q, item):
    """Đẩy dữ liệu vào queue an toàn, tránh tràn bộ nhớ"""
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
            q.put_nowait(item)
        except:
            pass

def slugify_and_truncate(name: str, max_length: int = 100):
    """Cắt ngắn và làm sạch tên file để tránh lỗi Android"""
    if not name: return "file"
    name = unicodedata.normalize("NFKD", name)
    name = re.sub(r'[^\w\s\.-]', '', name).strip()
    name = re.sub(r'\s+', ' ', name)
    if len(name) <= max_length: return name
    
    parts = os.path.splitext(name)
    # Giữ lại đuôi file
    base = parts[0][: max_length - len(parts[1]) - 1]
    return base + parts[1]

def safe_rename_downloaded_file(filepath: str, max_title_len: int = 80):
    """Đổi tên file sau khi tải để đảm bảo an toàn"""
    try:
        if not filepath or not os.path.exists(filepath): return filepath
        folder, fname = os.path.split(filepath)
        title, ext = os.path.splitext(fname)
        
        # Thử tách phần ID phía sau (thường yt-dlp thêm ID vào cuối)
        parts = title.rsplit('-', 1)
        if len(parts) == 2 and len(parts[1]) <= 20 and all(c.isalnum() for c in parts[1]):
            base, idpart = parts
            new_base = slugify_and_truncate(base, max_length=max_title_len)
            new_name = f"{new_base}-{idpart}{ext}"
        else:
            new_base = slugify_and_truncate(title, max_length=max_title_len)
            new_name = f"{new_base}{ext}"
            
        new_path = os.path.join(folder, new_name)
        
        # Tránh ghi đè file cũ
        i = 1
        candidate = new_path
        while os.path.exists(candidate) and candidate != filepath:
            candidate = os.path.join(folder, f"{os.path.splitext(new_name)[0]}_{i}{ext}")
            i += 1
            
        if candidate != filepath:
            os.rename(filepath, candidate)
            return candidate
        return filepath
    except:
        return filepath

# --- MAIN APP ---

def main(page: ft.Page):
    # 1. CẤU HÌNH PAGE
    page.title = "HUST Downloader Ultimate"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = COLOR_BG
    page.padding = 10
    
    # [QUAN TRỌNG] Giữ màn hình sáng để không bị ngắt tải (Fix lỗi Sleep Mode)
    page.platform = ft.PagePlatform.ANDROID
    page.keep_screen_on = True 

    # Responsive
    try:
        win_w = page.window_width or 800
    except:
        win_w = 800
    ctrl_width = min(760, max(360, int(win_w * 0.9)))

    # State Management
    progress_queue = queue.Queue(maxsize=2000)
    cancel_event = threading.Event()
    
    # Load Settings & History
    default_settings = {"smart_clipboard": True, "cookies": "", "theme_color": "red"}
    raw_settings = page.client_storage.get(SETTINGS_KEY)
    user_settings = raw_settings if isinstance(raw_settings, dict) else default_settings
    
    raw_history = page.client_storage.get(HISTORY_KEY)
    download_history = raw_history if isinstance(raw_history, list) else []

    # --- UI COMPONENTS ---
    
    txt_url = ft.TextField(label="Dán Link Video...", prefix_icon=ft.icons.LINK, bgcolor="#1e1e1e", border_radius=10, width=ctrl_width)
    
    # Tự động tìm đường dẫn lưu
    def detect_default_path():
        candidates = [
            "/storage/emulated/0/Download", 
            "/storage/emulated/0/Downloads",
            "/storage/emulated/0/DCIM", 
            os.path.join(os.path.expanduser("~"), "Download"), 
            "." 
        ]
        for p in candidates:
            if os.path.exists(p): return p
        return "."
    
    txt_save_path = ft.TextField(label="Thư mục lưu", value=detect_default_path(), width=ctrl_width, text_size=12)
    
    dd_quality = ft.Dropdown(
        label="Chọn chất lượng", options=[], visible=False, 
        prefix_icon=ft.icons.VIDEO_SETTINGS, bgcolor="#1e1e1e", 
        border_radius=10, width=ctrl_width
    )
    
    sw_playlist = ft.Switch(label="Tải toàn bộ Playlist", value=False, visible=False)
    lbl_info = ft.Text("", color="grey", size=12)
    prg_bar = ft.ProgressBar(width=ctrl_width, color="orange", bgcolor="#333333", visible=False, value=0)
    lbl_status = ft.Text("Sẵn sàng", size=14, color="green", text_align="center")
    
    # Log Window
    log_field = ft.TextField(label="Nhật ký (Logs)", multiline=True, read_only=True, expand=True, height=150, value="", text_size=10, bgcolor="black", color="#00FF00")

    btn_analyze = ft.ElevatedButton("PHÂN TÍCH LINK", icon=ft.icons.ANALYTICS, bgcolor="blue", color="white", width=180)
    btn_download = ft.ElevatedButton("TẢI XUỐNG", icon=ft.icons.DOWNLOAD, bgcolor="green", color="white", width=180, visible=False)
    btn_cancel = ft.ElevatedButton("HỦY", icon=ft.icons.CANCEL, bgcolor="red", color="white", visible=False, disabled=True)
    
    txt_cookies = ft.TextField(label="Cookies (Netscape format)", multiline=True, min_lines=3, max_lines=5, hint_text="Dán nội dung cookies.txt", text_size=12, value=user_settings.get("cookies", ""))
    sw_smart_clip = ft.Switch(label="Tự động bắt Link", value=user_settings.get("smart_clipboard", True))
    btn_save_settings = ft.ElevatedButton("LƯU CÀI ĐẶT", icon=ft.icons.SAVE, bgcolor=COLOR_PRIMARY, color="white")

    # --- HELPERS ---
    def add_log(msg: str):
        # Không update page ở đây để tránh lag, chỉ cập nhật biến value
        now = datetime.now().strftime("%H:%M:%S")
        new = f"{now} | {msg}\n"
        log_field.value = (new + log_field.value)[:10000]

    def prepare_save_path(path: str):
        try:
            if not path: path = "."
            os.makedirs(path, exist_ok=True)
            testfile = os.path.join(path, ".hust_write_test")
            with open(testfile, "w") as f: f.write("ok")
            os.remove(testfile)
            return True, path
        except Exception as ex:
            return False, str(ex)

    def save_history(item):
        nonlocal download_history
        if not isinstance(item, dict): return
        download_history.insert(0, item)
        download_history = download_history[:50]
        page.client_storage.set(HISTORY_KEY, download_history)
        update_history_tab()

    # --- WORKERS (LOGIC) ---

    def run_analyze(url, q):
        try:
            import yt_dlp
            # Kiểm tra FFmpeg (Fix lỗi video câm)
            has_ffmpeg = shutil.which("ffmpeg") is not None
            
            opts = {
                'quiet': True, 'no_warnings': True, 'extract_flat': True,
                'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                is_playlist = False
                if isinstance(info, dict) and 'entries' in info:
                    is_playlist = True
                    # Lấy video con đầu tiên để phân tích format
                    try:
                        first = info['entries'][0]
                        sub_url = first.get('url') or first.get('id')
                        info = ydl.extract_info(sub_url, download=False)
                    except: pass 
                
                formats = info.get('formats', [])
                formats = [f for f in formats if isinstance(f, dict)]
                formats.sort(key=lambda x: x.get('height') or 0, reverse=True)
                
                options = []
                options.append({"key": "audio", "text": "🎵 Audio M4A (Nhạc)"})
                seen = set()
                
                for f in formats:
                    fid = f.get('format_id')
                    h = f.get('height')
                    ext = f.get('ext')
                    acodec = f.get('acodec') # Codec âm thanh
                    
                    if h and ext in ['mp4', 'webm'] and h >= 144:
                        # [FIX QUAN TRỌNG] Nếu không có FFmpeg VÀ video không tiếng -> Bỏ qua
                        if not has_ffmpeg and acodec == 'none':
                            continue
                            
                        if h not in seen:
                            seen.add(h)
                            note = ""
                            if acodec == 'none': note = " (🔇 Không tiếng)"
                            options.append({"key": fid, "text": f"🎬 Video {h}p ({ext}){note}"})
                            
                q.put({'type': 'analyze_done', 'options': options, 'title': info.get('title', 'Unknown'), 'is_playlist': is_playlist})
        except Exception as e:
            safe_put(q, {'type': 'error', 'msg': f"Lỗi phân tích: {e}"})

    def run_download(url, quality_id, is_playlist, save_path, cookie_content, cancel_evt, q):
        cookie_file = None
        last_filepath = None
        try:
            import yt_dlp
            from yt_dlp.utils import DownloadError
            
            ok, msg = prepare_save_path(save_path)
            if not ok:
                safe_put(q, {'type': 'error', 'msg': f"Lỗi thư mục: {msg}"})
                return

            if cookie_content and cookie_content.strip():
                tf = tempfile.NamedTemporaryFile(mode="w", delete=False, prefix="hust_", suffix=".txt")
                tf.write(cookie_content)
                tf.flush(); tf.close()
                cookie_file = tf.name

            def progress_hook(d):
                nonlocal last_filepath
                if cancel_evt.is_set(): raise DownloadError("HUST_CANCELLED")
                if d.get('status') == 'finished':
                    last_filepath = d.get('filename')
                safe_put(q, {'type': 'progress', 'd': d})

            has_ffmpeg = shutil.which("ffmpeg") is not None
            if not has_ffmpeg: safe_put(q, {'type': 'log', 'msg': 'Không có FFmpeg -> Chế độ tương thích.'})

            # [FIX] Tên file an toàn + Cấu hình mạng trâu bò
            outtmpl = os.path.join(save_path, "%(title).50s-%(id)s.%(ext)s")
            
            opts = {
                'outtmpl': outtmpl,
                'quiet': True, 'no_warnings': True, 'nocheckcertificate': True,
                'restrictfilenames': True,
                'progress_hooks': [progress_hook],
                'http_headers': {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'},
                'noplaylist': not bool(is_playlist),
                'socket_timeout': 30, 'retries': 10, 'fragment_retries': 10 # [FIX] Mạng lag
            }
            if cookie_file: opts['cookiefile'] = cookie_file

            media_type = 'video'
            if quality_id == "audio":
                opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
                media_type = 'audio'
            elif quality_id:
                if has_ffmpeg:
                    opts['format'] = f"{quality_id}+bestaudio/best"
                else:
                    opts['format'] = f"{quality_id}/best[ext=mp4]/best"
            else:
                opts['format'] = "best[ext=mp4]/best"

            safe_put(q, {'type': 'status', 'msg': 'Đang kết nối Server...'})
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
                
                # [FIX] Đổi tên file an toàn sau khi tải
                final_path = last_filepath
                if last_filepath:
                    final_path = safe_rename_downloaded_file(last_filepath)
                
                safe_put(q, {'type': 'finished', 'title': os.path.basename(final_path) if final_path else 'Done', 'filepath': final_path, 'media_type': media_type})

        except Exception as e:
            text = str(e)
            if 'HUST_CANCELLED' in text or 'Cancelled' in text:
                safe_put(q, {'type': 'cancelled'})
            else:
                safe_put(q, {'type': 'error', 'msg': text})
        finally:
            if cookie_file and os.path.exists(cookie_file):
                try: os.remove(cookie_file)
                except: pass
            safe_put(q, {'type': 'worker_done'})

    # --- UI EVENT HANDLERS ---

    def analyze_click(e):
        url = txt_url.value.strip()
        if not url:
            lbl_status.value = "Chưa nhập Link!"; lbl_status.color = "red"; page.update()
            return
        btn_analyze.disabled = True
        lbl_status.value = "Đang phân tích..."; lbl_status.color = "yellow"
        prg_bar.visible = True; prg_bar.value = None
        dd_quality.visible = False; btn_download.visible = False; sw_playlist.visible = False
        page.update()
        threading.Thread(target=run_analyze, args=(url, progress_queue), daemon=True).start()

    def download_click(e):
        url = txt_url.value.strip()
        quality_id = dd_quality.value
        is_playlist = sw_playlist.value
        save_path = txt_save_path.value.strip() or "."
        
        ok, msg = prepare_save_path(save_path)
        if not ok:
            add_log(f"Lỗi Path: {msg}")
            lbl_status.value = "Thư mục lỗi"; lbl_status.color = "red"; page.update()
            return

        btn_download.visible = False; btn_analyze.visible = False
        btn_cancel.visible = True; btn_cancel.disabled = False
        dd_quality.disabled = True
        lbl_status.value = "Đang khởi động..."; prg_bar.visible = True; prg_bar.value = 0
        page.update()
        
        cancel_event.clear()
        threading.Thread(target=run_download, args=(url, quality_id, is_playlist, save_path, txt_cookies.value, cancel_event, progress_queue), daemon=True).start()

    def cancel_click_handler(e):
        if not cancel_event.is_set():
            cancel_event.set()
            lbl_status.value = "Đang dừng..."; page.update()

    btn_analyze.on_click = analyze_click
    btn_download.on_click = download_click
    btn_cancel.on_click = cancel_click_handler
    
    # Paste Button
    def paste_click(e):
        try: txt_url.value = page.get_clipboard() or ""; txt_url.update()
        except: pass
    txt_url.suffix = ft.IconButton(ft.icons.PASTE, on_click=paste_click)

    # Save Settings
    def save_settings_click(e):
        new_settings = {"cookies": txt_cookies.value, "smart_clipboard": sw_smart_clip.value, "theme_color": "red"}
        page.client_storage.set(SETTINGS_KEY, new_settings)
        page.show_snack_bar(ft.SnackBar(content=ft.Text("Đã lưu cài đặt!"), bgcolor="green"))
    btn_save_settings.on_click = save_settings_click

    # --- TABS & LAYOUT ---

    # History List
    lv_history = ft.ListView(expand=True, spacing=10)
    def update_history_tab():
        lv_history.controls.clear()
        if not download_history:
            lv_history.controls.append(ft.Text("Chưa có lịch sử", italic=True, text_align="center"))
        else:
            for item in download_history:
                icon = ft.icons.MUSIC_NOTE if item.get('type') == 'audio' else ft.icons.VIDEO_FILE
                lv_history.controls.append(
                    ft.Container(
                        content=ft.Row([
                            ft.Icon(icon, color="orange"),
                            ft.Column([
                                ft.Text(item.get('title',''), weight="bold", no_wrap=True, max_lines=1, width=200),
                                ft.Text(f"{item.get('date')} | {item.get('path')}", size=10, color="grey")
                            ], spacing=2),
                            ft.Icon(ft.icons.CHECK_CIRCLE, color="green", size=16)
                        ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        bgcolor="#1e1e1e", padding=10, border_radius=10
                    )
                )
        page.update()

    tab_home = ft.Container(
        content=ft.Column([
            ft.Icon(ft.icons.ROCKET_LAUNCH_ROUNDED, size=60, color=COLOR_PRIMARY),
            ft.Text("HUST DOWNLOADER", size=24, weight="bold"),
            ft.Text(VERSION, size=12, color="grey"),
            ft.Container(height=10),
            txt_url,
            ft.Container(height=5),
            txt_save_path,
            ft.Container(height=5),
            lbl_info,
            sw_playlist,
            dd_quality,
            ft.Container(height=10),
            ft.Row([btn_analyze, btn_download, btn_cancel], alignment=ft.MainAxisAlignment.CENTER),
            ft.Container(height=10),
            lbl_status,
            prg_bar,
            ft.Container(height=10),
            log_field
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=10
    )

    tab_history = ft.Container(content=ft.Column([
        ft.Text("Lịch sử", size=20, weight="bold"),
        ft.ElevatedButton("Xóa lịch sử", icon=ft.icons.DELETE, on_click=lambda e: (download_history.clear(), page.client_storage.remove(HISTORY_KEY), update_history_tab()), bgcolor="red"),
        ft.Divider(), lv_history
    ]), padding=10)

    tab_settings = ft.Container(content=ft.Column([
        ft.Text("Cấu hình", size=20, weight="bold"),
        ft.Container(height=10), sw_smart_clip, ft.Divider(),
        ft.Text("Quản lý Cookie:", weight="bold"), txt_cookies,
        ft.Container(height=20), btn_save_settings
    ]), padding=10)

    tabs = ft.Tabs(selected_index=0, animation_duration=300, tabs=[
        ft.Tab(text="Tải xuống", icon=ft.icons.DOWNLOAD),
        ft.Tab(text="Lịch sử", icon=ft.icons.HISTORY),
        ft.Tab(text="Cài đặt", icon=ft.icons.SETTINGS)
    ], expand=1)
    
    tabs.tabs[0].content = tab_home
    tabs.tabs[1].content = tab_history
    tabs.tabs[2].content = tab_settings
    page.add(tabs)
    update_history_tab()

    # Smart Clipboard
    if user_settings.get("smart_clipboard"):
        try:
            clip = page.get_clipboard()
            if clip and "http" in clip and clip != txt_url.value:
                txt_url.value = clip; page.show_snack_bar(ft.SnackBar(content=ft.Text("Đã bắt link!")))
        except: pass

    # --- QUEUE POLLING ---
    last_percent = 0.0
    last_ui_time = 0.0
    
    def poll_queue(evt):
        nonlocal last_percent, last_ui_time
        any_update = False
        while not progress_queue.empty():
            item = progress_queue.get_nowait()
            t = item.get('type')
            
            if t == 'analyze_done':
                opts = []
                for opt in item.get('options', []):
                    try: opts.append(ft.dropdown.Option(key=opt['key'], text=opt['text']))
                    except: continue
                dd_quality.options = opts
                if opts: dd_quality.value = opts[0].key
                
                lbl_info.value = f"Tiêu đề: {item.get('title','')}"
                if item.get('is_playlist'):
                    sw_playlist.visible = True; sw_playlist.value = False
                    lbl_info.value += " (Playlist)"
                
                dd_quality.visible = True; btn_download.visible = True
                btn_analyze.disabled = False; prg_bar.visible = False
                lbl_status.value = "Đã phân tích xong!"; lbl_status.color = "blue"
                any_update = True
                
            elif t == 'progress':
                d = item.get('d', {})
                if d.get('status') == 'downloading':
                    try:
                        p = float(str(d.get('_percent_str', '0%')).replace('%','').strip())/100.0
                    except: p = 0.0
                    now = time.time()
                    if abs(p - last_percent) >= 0.005 or (now - last_ui_time) > 0.2:
                        last_percent = p; last_ui_time = now
                        prg_bar.value = p
                        lbl_status.value = f"Đang tải: {d.get('_percent_str')} | {d.get('_speed_str')}"
                        any_update = True
                        
            elif t == 'finished':
                lbl_status.value = "✅ HOÀN TẤT!"; lbl_status.color = "green"
                prg_bar.value = 1
                fname = item.get('filepath') or "file"
                add_log(f"Xong: {fname}")
                page.show_snack_bar(ft.SnackBar(content=ft.Text("Đã lưu thành công!"), bgcolor="green"))
                save_history({
                    "title": item.get('title', 'Unknown'),
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    "path": fname,
                    "type": item.get('media_type', 'video')
                })
                any_update = True
                
            elif t == 'cancelled':
                lbl_status.value = "⛔ ĐÃ HỦY"; lbl_status.color = "grey"
                add_log("User Cancelled")
                any_update = True
                
            elif t == 'error':
                msg = str(item.get('msg'))
                lbl_status.value = "❌ Lỗi (Xem Log)"; lbl_status.color = "red"
                add_log(f"ERR: {msg}")
                any_update = True
                
            elif t == 'log':
                add_log(item.get('msg'))
                any_update = True
                
            elif t == 'worker_done':
                btn_download.visible = True; btn_cancel.visible = False; btn_cancel.disabled = True
                btn_analyze.visible = True; btn_analyze.disabled = False
                dd_quality.disabled = False; prg_bar.visible = False
                any_update = True

        if any_update: page.update()

    timer = ft.Timer(0.15, poll_queue)
    timer.autostart = True
    page.overlay.append(timer)

ft.app(target=main)