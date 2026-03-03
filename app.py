from flask import Flask, render_template, request, jsonify, send_file, after_this_request
from flask_socketio import SocketIO, emit
import yt_dlp
import os
import threading
import uuid
import time
import shutil
import sys

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='threading')

# --- CẤU HÌNH ---
BASE_DIR = os.path.abspath(os.getcwd())
DOWNLOAD_FOLDER = os.path.join(BASE_DIR, 'downloads')
FFMPEG_PATH = os.path.join(BASE_DIR, 'ffmpeg.exe')
COOKIES_PATH = os.path.join(BASE_DIR, 'cookies.txt')

# Nếu có ffmpeg.exe trong thư mục gốc, thêm vào PATH để yt-dlp tìm thấy
if os.path.exists(FFMPEG_PATH):
    os.environ["PATH"] = BASE_DIR + os.pathsep + os.environ["PATH"]

# Tạo thư mục downloads nếu chưa có
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)


class SocketLogger:
    """
    Bộ ghi log tùy chỉnh dành cho yt-dlp.
    Thay vì in ra terminal, tất cả log được gửi thẳng lên giao diện
    người dùng qua WebSocket (sự kiện 'log_update').
    Bỏ qua các dòng [debug] để tránh spam log.
    """
    def debug(self, msg):
        if not msg.startswith('[debug] '): socketio.emit('log_update', {'data': msg})
    def info(self, msg): socketio.emit('log_update', {'data': msg})
    def warning(self, msg): socketio.emit('log_update', {'data': f"WARNING: {msg}"})
    def error(self, msg): socketio.emit('log_update', {'data': f"ERROR: {msg}"})


@app.route('/')
def index():
    """Trả về trang giao diện chính (templates/index.html)."""
    return render_template('index.html')


def get_ydl_opts(base_opts):
    """
    Inject thêm tùy chọn cookies vào cấu hình yt-dlp nếu file cookies.txt tồn tại.
    Dùng để tải các video yêu cầu đăng nhập (ví dụ: video giới hạn tuổi trên YouTube).
    Trả về dict cấu hình đã được bổ sung (hoặc giữ nguyên nếu không có cookies).
    """
    if os.path.exists(COOKIES_PATH):
        base_opts['cookiefile'] = COOKIES_PATH
        print(f"[DEBUG] Đang dùng Cookies từ: {COOKIES_PATH}")
    return base_opts


@app.route('/get_video_info', methods=['POST'])
def get_video_info():
    """
    API endpoint: Quét thông tin video/playlist từ URL mà không tải file.
    Nhận vào: JSON body có trường 'url'.
    Trả về: JSON chứa tiêu đề, thumbnail, thời lượng, tác giả, và danh sách
    độ phân giải có sẵn. Nếu là playlist, trả về số lượng bài thay cho thời lượng.
    """
    url = request.json.get('url')

    if 'spotify.com' in url:
        return jsonify({'status': 'error', 'message': 'Hệ thống chưa hỗ trợ Spotify.'})

    try:
        # Quét nhanh, không tải file, không hiện cảnh báo
        opts = {'noplaylist': True, 'quiet': True, 'no_warnings': True}
        opts = get_ydl_opts(opts)

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)

            if 'entries' in info:
                # Đây là Playlist / Album
                title = info.get('title', 'Album/Playlist')
                count = len(list(info['entries']))
                return jsonify({
                    'status': 'success',
                    'title': f"[Album] {title}",
                    'thumbnail': 'https://music.youtube.com/img/favicon_144.png',
                    'duration': f"{count} bài hát",
                    'author': info.get('uploader', 'YouTube Music'),
                    'resolutions': [{'height': 'Zip', 'fps': 'Download All'}]
                })
            else:
                # Đây là video lẻ — thu thập các độ phân giải có video stream thật
                formats = info.get('formats', [])
                resolutions = set()
                for f in formats:
                    if f.get('vcodec') != 'none' and f.get('height'):
                        resolutions.add(f['height'])

                sorted_res = sorted(list(resolutions), reverse=True)
                return jsonify({
                    'status': 'success',
                    'title': info.get('title'),
                    'thumbnail': info.get('thumbnail'),
                    'duration': info.get('duration_string'),
                    'author': info.get('uploader'),
                    'resolutions': sorted_res
                })

    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})


def process_download(url, format_type, quality):
    """
    Hàm xử lý tải xuống chính, chạy trong một thread riêng biệt.
    Luồng xử lý:
      1. Kiểm tra URL có phải playlist hay video lẻ.
      2. Tạo thư mục tạm riêng (downloads/yt_<uuid>/) để chứa file đang tải.
      3. Cấu hình yt-dlp theo định dạng yêu cầu (MP3 / MP4 / GIF).
      4. Tải xong: nếu playlist thì nén ZIP, nếu lẻ thì chuyển file ra ngoài.
      5. Dọn dẹp thư mục tạm, phát sự kiện 'download_complete' về trình duyệt.
    Nếu có lỗi bất kỳ, phát sự kiện 'download_error' và xóa thư mục tạm.
    """
    file_id = str(uuid.uuid4())
    final_file_id = ""
    user_filename = "media"
    work_dir = ""

    try:
        if 'spotify.com' in url:
            socketio.emit('log_update', {'data': 'LỖI: Spotify không hỗ trợ.'})
            return

        # Không cho tải GIF từ YouTube Music vì đây là link nhạc, không có video
        if 'music.youtube.com' in url and format_type == 'gif':
            socketio.emit('log_update', {'data': 'LỖI: Không thể tạo GIF từ link nhạc (YouTube Music). Vui lòng chọn MP3 hoặc MP4.'})
            socketio.emit('download_error')
            return

        # Bước 1: Kiểm tra Playlist hay Video lẻ bằng extract_flat (nhanh, không tải)
        opts_check = {'extract_flat': True, 'quiet': True}
        opts_check = get_ydl_opts(opts_check)

        with yt_dlp.YoutubeDL(opts_check) as ydl:
            info_dict = ydl.extract_info(url, download=False)

        # Nếu có 'entries' thì là playlist/album
        is_playlist = 'entries' in info_dict
        playlist_title = info_dict.get('title', 'Album')

        # Bước 2: Tạo thư mục làm việc tạm, đặt tên theo UUID để tránh xung đột
        work_dir = os.path.join(DOWNLOAD_FOLDER, f"yt_{file_id}")
        if not os.path.exists(work_dir): os.makedirs(work_dir)

        # Bước 3: Cấu hình yt-dlp — gắn logger WebSocket và cấu hình metadata
        ydl_opts = {
            'logger': SocketLogger(),
            'progress_hooks': [lambda d: socketio.emit('log_update', {'data': f"Tiến độ: {d.get('_percent_str', '0%')}"}) if d['status'] == 'downloading' else None],
            'noplaylist': False if is_playlist else True,
            # Tự động parse metadata từ YouTube Music
            'parse_metadata': [
                {'from': 'title', 'regex': r'(?P<title>.+)', 'replace': r'\g<title>'},
                {'from': 'uploader', 'regex': r'(?P<artist>.+)', 'replace': r'\g<artist>'},
                # Ưu tiên lấy năm phát hành gốc (release_date/release_year) thay vì upload_date
                {'from': 'release_year', 'regex': r'(?P<meta_date>.+)', 'replace': r'\g<meta_date>'},
                {'from': 'release_date', 'regex': r'(?P<meta_date>.+)', 'replace': r'\g<meta_date>'},
            ],
            'addmetadata': True,
            'writethumbnail': True,
        }

        if is_playlist:
            # Đặt tên file theo thứ tự trong album: "01. Tên Bài.mp3"
            ydl_opts['outtmpl'] = os.path.join(work_dir, '%(playlist_index)s. %(title)s.%(ext)s')
            socketio.emit('log_update', {'data': f"Phát hiện Album: {playlist_title}. Đang tải toàn bộ..."})
        else:
            ydl_opts['outtmpl'] = os.path.join(work_dir, '%(title)s.%(ext)s')

        ydl_opts = get_ydl_opts(ydl_opts)

        # Cấu hình định dạng đầu ra theo lựa chọn của người dùng
        if format_type == 'mp3':
            # Tải audio tốt nhất, convert sang MP3 320kbps, nhúng ảnh bìa và ID3 tag
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [
                    {'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '320'},
                    {'key': 'FFmpegMetadata', 'add_metadata': True},
                    {'key': 'EmbedThumbnail'},
                ],
            })
        elif format_type == 'gif':
            # Tải video tốt nhất rồi convert sang GIF qua FFmpeg
            ydl_opts.update({'format': 'bestvideo/best','postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'gif'}]})
        else: # MP4
            # Ghép video + audio tốt nhất theo độ phân giải được chọn
            if quality == 'best': format_str = 'bestvideo+bestaudio/best'
            else: format_str = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
            ydl_opts.update({'format': format_str, 'merge_output_format': 'mp4','postprocessors': [{'key': 'FFmpegMetadata'}, {'key': 'EmbedThumbnail'}]})

        # Bước 4: Bắt đầu tải — yt-dlp tự xử lý toàn bộ, log qua SocketLogger
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # Bước 5: Xử lý file sau khi tải xong
        downloaded_files = os.listdir(work_dir)
        # Lọc chỉ giữ file media, bỏ qua file ảnh bìa (.jpg, .webp, ...) do yt-dlp tạo ra
        valid_extensions = ('.mp3', '.mp4', '.gif', '.m4a', '.wav')
        media_files = [f for f in downloaded_files if f.lower().endswith(valid_extensions)]

        if not media_files:
            raise Exception("Không tải được file nào!")

        if is_playlist or len(media_files) > 1:
            # Playlist / nhiều file: nén toàn bộ thư mục tạm thành một file ZIP
            socketio.emit('log_update', {'data': 'Đang nén file ZIP (Có Metadata)...'})
            shutil.make_archive(os.path.join(DOWNLOAD_FOLDER, file_id), 'zip', work_dir)
            final_file_id = f"{file_id}.zip"
            # Làm sạch tên album để dùng làm tên file ZIP
            safe_title = "".join([c for c in playlist_title if c.isalpha() or c.isdigit() or c in " .-_()"]).strip()
            user_filename = f"{safe_title}.zip"
        else:
            # Video lẻ: chuyển file ra khỏi thư mục tạm vào downloads/
            src_file = os.path.join(work_dir, media_files[0])
            ext = src_file.split('.')[-1]
            final_file_id = f"{file_id}.{ext}"
            user_filename = media_files[0]
            if os.path.exists(os.path.join(DOWNLOAD_FOLDER, final_file_id)):
                os.remove(os.path.join(DOWNLOAD_FOLDER, final_file_id))
            shutil.move(src_file, os.path.join(DOWNLOAD_FOLDER, final_file_id))

        # Dọn dẹp thư mục tạm và báo hoàn tất cho trình duyệt
        shutil.rmtree(work_dir, ignore_errors=True)
        socketio.emit('download_complete', {'file_id': final_file_id, 'user_filename': user_filename})

    except Exception as e:
        socketio.emit('log_update', {'data': f"LỖI: {str(e)}"})
        socketio.emit('download_error')
        if work_dir and os.path.exists(work_dir): shutil.rmtree(work_dir, ignore_errors=True)


@socketio.on('start_download')
def handle_download(data):
    """
    Lắng nghe sự kiện WebSocket 'start_download' từ trình duyệt.
    Tạo một thread mới để chạy process_download() nhằm tránh block server
    trong lúc đang tải (quá trình tải có thể mất vài phút).
    """
    thread = threading.Thread(target=process_download, args=(data['url'], data['format'], data.get('quality', 'best')))
    thread.start()


def secure_delete(file_path):
    """
    Xóa file sau một khoảng thời gian chờ (10 giây).
    Chạy trong thread riêng, được gọi ngay sau khi file được gửi về trình duyệt.
    Mục đích: đảm bảo trình duyệt kịp nhận file trước khi server xóa.
    """
    time.sleep(10)
    try:
        if os.path.exists(file_path): os.remove(file_path)
    except: pass


@app.route('/get_file/<file_id>')
def get_file(file_id):
    """
    API endpoint: Phục vụ file đã tải về cho trình duyệt dưới dạng attachment.
    Nhận tên file gốc qua query param 'name' để trình duyệt hiển thị đúng tên khi lưu.
    Sau khi gửi xong, lên lịch xóa file trên server sau 10 giây (qua secure_delete).
    """
    user_filename = request.args.get('name', 'file')
    file_path = os.path.join(DOWNLOAD_FOLDER, file_id)

    @after_this_request
    def remove_file(response):
        # Chạy xóa file trong thread riêng để không làm chậm response
        threading.Thread(target=secure_delete, args=(file_path,)).start()
        return response

    return send_file(file_path, as_attachment=True, download_name=user_filename)


if __name__ == '__main__':
    print("--- SERVER SẴN SÀNG (YOUTUBE MUSIC ALBUM SUPPORT) ---")
    socketio.run(app, debug=True, port=5000)
