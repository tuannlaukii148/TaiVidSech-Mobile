import flet as ft
import yt_dlp
import os
import threading

# --- CẤU HÌNH LOGIC (CORE ENGINE) ---
# Mang tư duy từ bản PC sang, nhưng bỏ dependencies exe
class MobileDownloader:
    def __init__(self):
        # Đường dẫn download chuẩn trên Android
        self.download_path = "/storage/emulated/0/Download"
        # Fallback cho PC khi debug
        if not os.path.exists(self.download_path):
            self.download_path = "Downloads"

    def get_opts(self, url, settings, hook_func):
        """
        Cấu hình yt-dlp được tối ưu hóa từ bản PC V7.1
        nhưng loại bỏ FFmpeg/Aria2c để tương thích Android.
        """
        path_template = f'{self.download_path}/%(title)s.%(ext)s'
        
        # [QUAN TRỌNG] Headers giả lập trình duyệt (Lấy từ code PC của bạn)
        # Giúp tránh bị Youtube/Facebook chặn IP lạ
        fake_headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Sec-Fetch-Dest': 'document',
            'Connection': 'keep-alive',
        }

        opts = {
            'outtmpl': path_template,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'progress_hooks': [hook_func],
            'http_headers': fake_headers, # Áp dụng headers xịn
            
            # --- TỐI ƯU CHO MOBILE (KHÔNG CÓ FFMPEG) ---
            # Chỉ tải file nào có sẵn cả hình+tiếng (thường max 720p/1080p)
            'format': 'best[ext=mp4]/best', 
            
            # Nếu là Audio thì chỉ tải audio gốc (không convert sang mp3 được vì thiếu ffmpeg)
            # Nhưng vẫn nghe được trên điện thoại bình thường
        }

        # Logic Audio riêng
        if settings['type'] == 'audio':
            opts['format'] = 'bestaudio/best'

        # Logic Youtube SponsorBlock (Giữ lại tính năng hay này)
        if 'youtube' in url:
            opts['sponsorblock_remove'] = ['sponsor', 'intro', 'outro', 'selfpromo']

        return opts

# --- GIAO DIỆN NGƯỜI DÙNG (UI) ---
def main(page: ft.Page):
    # Cấu hình App
    page.title = "HUST Downloader Mobile"
    page.theme_mode = ft.ThemeMode.DARK
    page.vertical_alignment = ft.MainAxisAlignment.START
    page.padding = 20
    page.scroll = ft.ScrollMode.AUTO
    
    downloader = MobileDownloader()

    # --- UI COMPONENTS ---
    
    # 1. Header
    img_logo = ft.Icon(name=ft.icons.ROCKET_LAUNCH, size=50, color=ft.colors.ORANGE)
    lbl_title = ft.Text("HUST Downloader", size=24, weight="bold", color="orange")
    lbl_subtitle = ft.Text("Version Mobile 1.0 (Lite Core)", size=12, italic=True, color="grey")

    # 2. Input Area
    def paste_click(e):
        # Tính năng thay thế Auto-Clipboard: Bấm là dán
        txt_url.value = page.get_clipboard()
        txt_url.update()

    btn_paste = ft.IconButton(icon=ft.icons.PASTE, on_click=paste_click, tooltip="Dán link")
    txt_url = ft.TextField(
        label="Dán link Video vào đây...",
        hint_text="Youtube, TikTok, Facebook...",
        border_radius=15,
        suffix=btn_paste,
        text_size=14
    )

    # 3. Settings Area (Đơn giản hóa từ Wizard Mode)
    opt_type = ft.RadioGroup(
        content=ft.Row([
            ft.Radio(value="video", label="Video MP4"),
            ft.Radio(value="audio", label="Audio Only"),
        ]),
        value="video"
    )

    # 4. Progress Area
    prg_bar = ft.ProgressBar(width=400, color="orange", bgcolor="#333333", visible=False)
    lbl_status = ft.Text("Sẵn sàng", size=14, color="grey")
    
    # --- LOGIC TẢI (CHẠY ĐA LUỒNG) ---
    def btn_download_click(e):
        url = txt_url.value
        if not url:
            txt_url.error_text = "Vui lòng nhập link!"
            txt_url.update()
            return
        
        txt_url.error_text = None
        btn_action.disabled = True
        btn_action.text = "Đang xử lý..."
        prg_bar.visible = True
        prg_bar.value = None # Chạy không xác định lúc đầu
        lbl_status.value = "Đang kết nối..."
        lbl_status.color = "yellow"
        page.update()

        # Tạo thread riêng để không đơ UI
        threading.Thread(target=run_download_logic, args=(url, opt_type.value), daemon=True).start()

    def run_download_logic(url, type_val):
        settings = {'type': type_val}
        
        def hook(d):
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
                lbl_status.value = "Đang lưu file..."
                page.update()

        try:
            opts = downloader.get_opts(url, settings, hook)
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                title = info.get('title', 'Video')
                
                # Success UI
                lbl_status.value = "✅ XONG!"
                lbl_status.color = "green"
                page.snack_bar = ft.SnackBar(ft.Text(f"Đã lưu: {title}"), bgcolor="green")
                page.snack_bar.open = True
                
        except Exception as err:
            # Error UI
            lbl_status.value = "Thất bại."
            lbl_status.color = "red"
            page.snack_bar = ft.SnackBar(ft.Text(f"Lỗi: {str(err)}"), bgcolor="red")
            page.snack_bar.open = True
        finally:
            btn_action.disabled = False
            btn_action.text = "BẮT ĐẦU TẢI"
            prg_bar.visible = False
            page.update()

    btn_action = ft.ElevatedButton(
        text="BẮT ĐẦU TẢI",
        width=300,
        height=50,
        style=ft.ButtonStyle(
            bgcolor=ft.colors.ORANGE,
            color=ft.colors.WHITE,
            shape=ft.RoundedRectangleBorder(radius=10),
        ),
        on_click=btn_download_click
    )

    # --- LAYOUT LẮP RÁP ---
    page.add(
        ft.Column(
            [
                ft.Container(height=10),
                ft.Row([img_logo, ft.Column([lbl_title, lbl_subtitle])], alignment=ft.MainAxisAlignment.CENTER),
                ft.Divider(height=30, color="transparent"),
                
                ft.Container(
                    content=ft.Column([
                        ft.Text("1. Nhập Link:", weight="bold"),
                        txt_url,
                        ft.Divider(height=10, color="transparent"),
                        ft.Text("2. Chọn định dạng:", weight="bold"),
                        opt_type,
                        ft.Divider(height=20, color="transparent"),
                        btn_action,
                    ]),
                    padding=20,
                    bgcolor="#1a1a1a",
                    border_radius=20
                ),
                
                ft.Divider(height=20, color="transparent"),
                lbl_status,
                prg_bar,
                
                ft.Container(height=30),
                ft.Text("Lưu tại: Bộ nhớ trong > Download", size=10, color="grey")
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER
        )
    )

ft.app(target=main)