import flet as ft
import os
import threading
import time
import json

# --- CẤU HÌNH & HẰNG SỐ ---
VERSION = "v3.0 Ultimate"
# Màu chủ đạo (HUST Style)
COLOR_PRIMARY = "#d32f2f"  # Đỏ đậm
COLOR_SECONDARY = "#ffa000" # Cam vàng
COLOR_BG = "#121212"       # Đen Dark Mode

def main(page: ft.Page):
    # 1. CẤU HÌNH PAGE (GIAO DIỆN CHUYÊN NGHIỆP)
    page.title = "HUST Downloader Ultimate"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = COLOR_BG
    page.padding = 0  # Full màn hình
    page.scroll = ft.ScrollMode.ADAPTIVE
    
    # Font chữ hệ thống đẹp hơn
    page.fonts = {
        "Roboto": "https://github.com/google/fonts/raw/main/apache/roboto/Roboto-Regular.ttf"
    }
    page.theme = ft.Theme(font_family="Roboto")

    # --- STATE MANAGEMENT (LƯU CẤU HÌNH) ---
    def load_settings():
        try:
            return page.client_storage.get("user_settings") or {"mode": "video", "thumb": False, "sub": False}
        except:
            return {"mode": "video", "thumb": False, "sub": False}

    def save_settings():
        settings = {
            "mode": opt_mode.value,
            "thumb": chk_thumb.value,
            "sub": chk_sub.value
        }
        page.client_storage.set("user_settings", settings)

    user_prefs = load_settings()

    # --- UI COMPONENTS (THÀNH PHẦN GIAO DIỆN) ---

    # Header Gradient sang trọng
    header = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.icons.ROCKET_LAUNCH_ROUNDED, size=40, color="white"),
                ft.Column([
                    ft.Text("HUST DOWNLOADER", size=20, weight="bold", color="white"),
                    ft.Text(f"{VERSION} • No-FFmpeg Engine", size=12, color="white70")
                ], spacing=0)
            ], alignment=ft.MainAxisAlignment.CENTER),
        ], alignment=ft.MainAxisAlignment.CENTER),
        padding=ft.padding.only(top=50, bottom=20),
        gradient=ft.LinearGradient(
            begin=ft.alignment.top_left,
            end=ft.alignment.bottom_right,
            colors=[COLOR_PRIMARY, "#b71c1c"],
        ),
        border_radius=ft.border_radius.only(bottom_left=30, bottom_right=30)
    )

    # Input URL
    txt_url = ft.TextField(
        label="Dán liên kết Video vào đây",
        hint_text="Hỗ trợ: Youtube, TikTok, Facebook...",
        prefix_icon=ft.icons.LINK,
        border_radius=15,
        text_size=14,
        bgcolor="#1e1e1e",
        border_color=COLOR_PRIMARY
    )

    # Nút Paste Clipboard
    def paste_link(e):
        # Lưu ý: Trên Android đôi khi cần quyền, nhưng Flet xử lý khá tốt
        txt_url.value = page.get_clipboard()
        txt_url.update()
        
    btn_paste = ft.IconButton(ft.icons.PASTE, on_click=paste_link, tooltip="Dán Link")
    txt_url.suffix = btn_paste

    # Tùy chọn (Tabs Selection)
    opt_mode = ft.RadioGroup(
        content=ft.Row([
            ft.Radio(value="video", label="Video (MP4)"),
            ft.Radio(value="audio", label="Nhạc (M4A/MP3)"),
        ], alignment=ft.MainAxisAlignment.CENTER),
        value=user_prefs["mode"]
    )

    # Tùy chọn mở rộng (Checkbox)
    chk_thumb = ft.Checkbox(label="Tải Ảnh bìa (Thumbnail)", value=user_prefs["thumb"])
    chk_sub = ft.Checkbox(label="Tải Phụ đề (Subtitle)", value=user_prefs["sub"])

    # Progress Bar (Thanh tiến trình 7 màu)
    prg_bar = ft.ProgressBar(width=400, color=COLOR_SECONDARY, bgcolor="#333333", visible=False)
    lbl_status = ft.Text("Sẵn sàng tải xuống", size=14, color="grey", text_align=ft.TextAlign.CENTER)
    
    # Log Console (Nhìn cho giống Hacker/Chuyên nghiệp)
    txt_log = ft.Container(
        content=ft.Column([], scroll=ft.ScrollMode.ALWAYS),
        height=100,
        bgcolor="black",
        border_radius=10,
        padding=10,
        visible=False
    )

    def log(msg, color="green"):
        """Hàm ghi log vào màn hình"""
        txt_log.content.controls.append(ft.Text(f"> {msg}", color=color, size=12, font_family="Consolas"))
        txt_log.visible = True
        txt_log.update()

    # --- LOGIC CORE (TRÁI TIM CỦA APP) ---
    def run_download_process(url, mode, want_thumb, want_sub):
        try:
            # 1. Lazy Import (Chống đen màn hình)
            import yt_dlp
            
            # 2. Xác định đường dẫn lưu trữ (Quan trọng nhất trên Android)
            # Ưu tiên thư mục Download công khai
            save_path = "/storage/emulated/0/Download/HUST_Downloads"
            
            # Tạo thư mục nếu chưa có
            if not os.path.exists(save_path):
                try:
                    os.makedirs(save_path, exist_ok=True)
                except:
                    # Fallback: Nếu không tạo được ở Download, dùng thư mục App Data
                    save_path = "." 

            # 3. Cấu hình yt-dlp tối ưu cho Mobile (Deep Config)
            # Template tên file an toàn
            path_template = f'{save_path}/%(title)s [%(id)s].%(ext)s'

            opts = {
                'outtmpl': path_template,
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True,
                'ignoreerrors': True,
                
                # [FIX LỖI] Tên file ký tự lạ gây crash Android
                'restrictfilenames': True,
                
                # [FIX LỖI] Tránh bị chặn bởi Youtube/Tiktok
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.9',
                },

                # Hook tiến trình
                'progress_hooks': [lambda d: update_progress(d)],
            }

            # [LOGIC] Xử lý định dạng
            if mode == 'audio':
                # Ưu tiên m4a (AAC) vì Android chơi tốt hơn webm
                opts['format'] = 'bestaudio[ext=m4a]/bestaudio/best'
            else:
                # Video: Ưu tiên mp4 để tương thích thư viện ảnh
                opts['format'] = 'best[ext=mp4]/best'

            # [LOGIC] Tùy chọn thêm
            if want_thumb:
                opts['writethumbnail'] = True
            if want_sub:
                opts['writesubtitles'] = True
                opts['subtitleslangs'] = ['vi', 'en', 'all']

            # Bắt đầu tải
            lbl_status.value = "Đang kết nối máy chủ..."
            page.update()
            log("Đang khởi tạo yt-dlp engine...", "yellow")

            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Unknown File')
                
                lbl_status.value = "✅ HOÀN TẤT!"
                lbl_status.color = "green"
                log(f"Đã lưu: {title}", "cyan")
                log(f"Vị trí: {save_path}", "white")
                
                # Hiện thông báo nổi (Snackbar)
                page.show_snack_bar(ft.SnackBar(
                    content=ft.Text(f"Tải xong: {title}", color="white"),
                    bgcolor="green"
                ))

        except ImportError:
            lbl_status.value = "Lỗi cài đặt!"
            lbl_status.color = "red"
            log("Thiếu thư viện yt-dlp!", "red")
        except PermissionError:
            lbl_status.value = "Lỗi Quyền!"
            lbl_status.color = "red"
            log("Chưa cấp quyền truy cập bộ nhớ!", "red")
            page.show_snack_bar(ft.SnackBar(content=ft.Text("Hãy cấp quyền Bộ nhớ cho App!"), bgcolor="red"))
        except Exception as e:
            lbl_status.value = "Lỗi không xác định"
            lbl_status.color = "red"
            log(f"Error: {str(e)}", "red")
        finally:
            # Reset UI
            btn_action.disabled = False
            btn_action.text = "BẮT ĐẦU TẢI NGAY"
            prg_bar.visible = False
            page.update()

    # Hàm cập nhật progress bar an toàn (tránh lỗi NaN)
    def update_progress(d):
        if d['status'] == 'downloading':
            try:
                p = d.get('_percent_str', '0%').replace('%', '')
                val = float(p) / 100
                prg_bar.value = val
                lbl_status.value = f"Đang tải: {d.get('_percent_str')} | {d.get('_speed_str')}"
                page.update()
            except: pass
        elif d['status'] == 'finished':
            prg_bar.value = 1.0
            lbl_status.value = "Đang xử lý file..."
            page.update()

    # Sự kiện nút bấm
    def btn_click(e):
        url = txt_url.value
        if not url:
            txt_url.error_text = "Bạn chưa nhập Link!"
            txt_url.update()
            return
        
        txt_url.error_text = None
        
        # Lưu cấu hình người dùng
        save_settings()

        # UI Updates
        btn_action.disabled = True
        btn_action.text = "ĐANG XỬ LÝ..."
        prg_bar.visible = True
        prg_bar.value = None # Loading vô định ban đầu
        txt_log.content.controls.clear() # Xóa log cũ
        page.update()

        # Chạy đa luồng
        threading.Thread(
            target=run_download_process,
            args=(url, opt_mode.value, chk_thumb.value, chk_sub.value),
            daemon=True
        ).start()

    # Nút Hành động (Big Button)
    btn_action = ft.ElevatedButton(
        text="BẮT ĐẦU TẢI NGAY",
        width=300,
        height=55,
        style=ft.ButtonStyle(
            bgcolor=COLOR_PRIMARY,
            color="white",
            shape=ft.RoundedRectangleBorder(radius=15),
            elevation=5,
        ),
        on_click=btn_click
    )

    # Info Footer
    footer = ft.Container(
        content=ft.Column([
            ft.Text("Files lưu tại: Bộ nhớ trong > Download > HUST_Downloads", size=10, color="grey"),
            ft.Text("Developed by TuanNlauKii148", size=10, weight="bold", color="#555555"),
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=20
    )

    # --- LAYOUT LẮP RÁP ---
    container = ft.Container(
        content=ft.Column([
            header,
            ft.Container(height=20),
            
            # Card điều khiển chính
            ft.Container(
                content=ft.Column([
                    txt_url,
                    ft.Divider(height=20, color="transparent"),
                    
                    ft.Text("Cấu hình tải:", weight="bold", size=16),
                    opt_mode,
                    ft.Row([chk_thumb, chk_sub], alignment=ft.MainAxisAlignment.CENTER),
                    
                    ft.Divider(height=20, color="transparent"),
                    btn_action,
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=20,
                bgcolor="#1e1e1e",
                border_radius=20,
                margin=ft.margin.symmetric(horizontal=15)
            ),
            
            ft.Container(height=20),
            lbl_status,
            ft.Container(content=prg_bar, padding=ft.padding.symmetric(horizontal=40)),
            ft.Container(height=10),
            
            # Khu vực Log (Console)
            ft.Container(content=txt_log, padding=ft.padding.symmetric(horizontal=15)),
            
            footer
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER),
    )

    page.add(container)

ft.app(target=main)