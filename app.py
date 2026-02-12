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

# Setup PATH cho FFmpeg
if os.path.exists(FFMPEG_PATH):
    os.environ["PATH"] = BASE_DIR + os.pathsep + os.environ["PATH"]

if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

class SocketLogger:
    def debug(self, msg):
        if not msg.startswith('[debug] '): socketio.emit('log_update', {'data': msg})
    def info(self, msg): socketio.emit('log_update', {'data': msg})
    def warning(self, msg): socketio.emit('log_update', {'data': f"WARNING: {msg}"})
    def error(self, msg): socketio.emit('log_update', {'data': f"ERROR: {msg}"})

@app.route('/')
def index():
    return render_template('index.html')

# --- HÀM TẠO OPTIONS CHO YT-DLP ---
def get_ydl_opts(base_opts):
    if os.path.exists(COOKIES_PATH):
        base_opts['cookiefile'] = COOKIES_PATH
        print(f"[DEBUG] Đang dùng Cookies từ: {COOKIES_PATH}")
    return base_opts

# --- API QUÉT THÔNG TIN ---
@app.route('/get_video_info', methods=['POST'])
def get_video_info():
    url = request.json.get('url')
    
    if 'spotify.com' in url:
        return jsonify({'status': 'error', 'message': 'Hệ thống chưa hỗ trợ Spotify.'})

    try:
        # Cấu hình quét nhanh
        opts = {'noplaylist': True, 'quiet': True, 'no_warnings': True}
        opts = get_ydl_opts(opts)

        with yt_dlp.YoutubeDL(opts) as ydl:
            # extract_flat=True giúp quét Playlist cực nhanh (không cần lấy chi tiết từng bài)
            info = ydl.extract_info(url, download=False)
            
            # Xử lý kết quả trả về
            if 'entries' in info:
                # Đây là Playlist / Album
                title = info.get('title', 'Album/Playlist')
                count = len(list(info['entries']))
                return jsonify({
                    'status': 'success',
                    'title': f"[Album] {title}",
                    'thumbnail': 'https://music.youtube.com/img/favicon_144.png', # Icon mặc định cho playlist
                    'duration': f"{count} bài hát",
                    'author': info.get('uploader', 'YouTube Music'),
                    'resolutions': [{'height': 'Zip', 'fps': 'Download All'}]
                })
            else:
                # Đây là Video lẻ
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

# --- HÀM XỬ LÝ CHÍNH ---
def process_download(url, format_type, quality):
    file_id = str(uuid.uuid4())
    final_file_id = ""
    user_filename = "media"
    work_dir = ""

    try:
        if 'spotify.com' in url:
            socketio.emit('log_update', {'data': 'LỖI: Spotify không hỗ trợ.'})
            return

        # Kiểm tra logic: Không cho tải GIF từ YouTube Music
        if 'music.youtube.com' in url and format_type == 'gif':
            socketio.emit('log_update', {'data': 'LỖI: Không thể tạo GIF từ link nhạc (YouTube Music). Vui lòng chọn MP3 hoặc MP4.'})
            socketio.emit('download_error')
            return

        # 1. Kiểm tra Playlist hay Video lẻ
        opts_check = {'extract_flat': True, 'quiet': True}
        opts_check = get_ydl_opts(opts_check)
        
        with yt_dlp.YoutubeDL(opts_check) as ydl:
            info_dict = ydl.extract_info(url, download=False)
        
        # Nếu có 'entries' thì là playlist
        is_playlist = 'entries' in info_dict
        playlist_title = info_dict.get('title', 'Album')
        
        # 2. Tạo thư mục làm việc tạm
        work_dir = os.path.join(DOWNLOAD_FOLDER, f"yt_{file_id}")
        if not os.path.exists(work_dir): os.makedirs(work_dir)

        # 3. Cấu hình tải (Metadata Siêu Xịn)
        ydl_opts = {
            'logger': SocketLogger(),
            'progress_hooks': [lambda d: socketio.emit('log_update', {'data': f"Tiến độ: {d.get('_percent_str', '0%')}"}) if d['status'] == 'downloading' else None],
            'noplaylist': False if is_playlist else True,
            # Tự động parse metadata từ YouTube Music
            'parse_metadata': [
                {'from': 'title', 'regex': r'(?P<title>.+)', 'replace': r'\g<title>'},
                {'from': 'uploader', 'regex': r'(?P<artist>.+)', 'replace': r'\g<artist>'},
                # Cấu hình mới: Ưu tiên lấy năm phát hành gốc (release_date/release_year)
                # Nếu không có thì mới lấy upload_date
                {'from': 'release_year', 'regex': r'(?P<meta_date>.+)', 'replace': r'\g<meta_date>'},
                {'from': 'release_date', 'regex': r'(?P<meta_date>.+)', 'replace': r'\g<meta_date>'},
            ],
            # Ép thêm metadata vào file
            'addmetadata': True,
            'writethumbnail': True,
        }
        
        if is_playlist:
            # Nếu là Album: Đặt tên file theo thứ tự: 01. Tên Bài.mp3
            ydl_opts['outtmpl'] = os.path.join(work_dir, '%(playlist_index)s. %(title)s.%(ext)s')
            socketio.emit('log_update', {'data': f"Phát hiện Album: {playlist_title}. Đang tải toàn bộ..."})
        else:
            # Nếu là lẻ
            ydl_opts['outtmpl'] = os.path.join(work_dir, '%(title)s.%(ext)s')

        ydl_opts = get_ydl_opts(ydl_opts)

        # Cấu hình định dạng
        if format_type == 'mp3':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [
                    {'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '320'}, # 320kbps cho nét
                    {'key': 'FFmpegMetadata', 'add_metadata': True}, # Gắn Tag ID3
                    {'key': 'EmbedThumbnail'}, # Gắn ảnh bìa vào MP3
                ],
            })
        elif format_type == 'gif':
            ydl_opts.update({'format': 'bestvideo/best','postprocessors': [{'key': 'FFmpegVideoConvertor', 'preferedformat': 'gif'}]})
        else: # MP4
            if quality == 'best': format_str = 'bestvideo+bestaudio/best'
            else: format_str = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"
            ydl_opts.update({'format': format_str, 'merge_output_format': 'mp4','postprocessors': [{'key': 'FFmpegMetadata'}, {'key': 'EmbedThumbnail'}]})

        # 4. Bắt đầu tải
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        # 5. Xử lý file sau khi tải
        downloaded_files = os.listdir(work_dir)
        # Lọc bỏ mấy file ảnh bìa thừa (chỉ giữ mp3/mp4/gif)
        valid_extensions = ('.mp3', '.mp4', '.gif', '.m4a', '.wav')
        media_files = [f for f in downloaded_files if f.lower().endswith(valid_extensions)]

        if not media_files: 
            raise Exception("Không tải được file nào!")

        if is_playlist or len(media_files) > 1:
            # Nén Zip
            socketio.emit('log_update', {'data': 'Đang nén file ZIP (Có Metadata)...'})
            shutil.make_archive(os.path.join(DOWNLOAD_FOLDER, file_id), 'zip', work_dir)
            final_file_id = f"{file_id}.zip"
            # Tên file zip đẹp: "Ten_Album.zip"
            safe_title = "".join([c for c in playlist_title if c.isalpha() or c.isdigit() or c in " .-_()"]).strip()
            user_filename = f"{safe_title}.zip"
        else:
            # File lẻ
            src_file = os.path.join(work_dir, media_files[0])
            ext = src_file.split('.')[-1]
            final_file_id = f"{file_id}.{ext}"
            user_filename = media_files[0]
            # Xóa file cũ nếu trùng
            if os.path.exists(os.path.join(DOWNLOAD_FOLDER, final_file_id)):
                os.remove(os.path.join(DOWNLOAD_FOLDER, final_file_id))
            shutil.move(src_file, os.path.join(DOWNLOAD_FOLDER, final_file_id))

        # Dọn dẹp
        shutil.rmtree(work_dir, ignore_errors=True)
        socketio.emit('download_complete', {'file_id': final_file_id, 'user_filename': user_filename})

    except Exception as e:
        socketio.emit('log_update', {'data': f"LỖI: {str(e)}"})
        socketio.emit('download_error')
        if work_dir and os.path.exists(work_dir): shutil.rmtree(work_dir, ignore_errors=True)

@socketio.on('start_download')
def handle_download(data):
    thread = threading.Thread(target=process_download, args=(data['url'], data['format'], data.get('quality', 'best')))
    thread.start()

def secure_delete(file_path):
    time.sleep(10)
    try:
        if os.path.exists(file_path): os.remove(file_path)
    except: pass

@app.route('/get_file/<file_id>')
def get_file(file_id):
    user_filename = request.args.get('name', 'file')
    file_path = os.path.join(DOWNLOAD_FOLDER, file_id)
    @after_this_request
    def remove_file(response):
        threading.Thread(target=secure_delete, args=(file_path,)).start()
        return response
    return send_file(file_path, as_attachment=True, download_name=user_filename)

if __name__ == '__main__':
    print("--- SERVER SẴN SÀNG (YOUTUBE MUSIC ALBUM SUPPORT) ---")
    socketio.run(app, debug=True, port=5000)