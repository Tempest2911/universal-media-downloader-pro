from flask import Flask, render_template, request, jsonify, send_file, after_this_request
from flask_socketio import SocketIO, emit
import yt_dlp
import os
import threading
import uuid
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='threading')

DOWNLOAD_FOLDER = os.path.join(os.getcwd(), 'downloads')
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

class SocketLogger:
    def debug(self, msg):
        if not msg.startswith('[debug] '):
            socketio.emit('log_update', {'data': msg})
    def info(self, msg):
        socketio.emit('log_update', {'data': msg})
    def warning(self, msg):
        socketio.emit('log_update', {'data': f"WARNING: {msg}"})
    def error(self, msg):
        socketio.emit('log_update', {'data': f"ERROR: {msg}"})

@app.route('/')
def index():
    return render_template('index.html')

# --- API MỚI: Lấy thông tin video và danh sách độ phân giải ---
@app.route('/get_video_info', methods=['POST'])
def get_video_info():
    url = request.json.get('url')
    try:
        ydl_opts = {'noplaylist': True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Lọc ra các độ phân giải video có sẵn
            formats = info.get('formats', [])
            resolutions = set()
            for f in formats:
                if f.get('vcodec') != 'none' and f.get('height'):
                    resolutions.add(f['height'])
            
            # Sắp xếp giảm dần (4K -> 1080p -> ...)
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

# --- Hàm xử lý tải xuống (Đã nâng cấp Metadata & Chọn độ phân giải) ---
def process_download(url, format_type, quality):
    try:
        file_id = str(uuid.uuid4())
        
        # Cấu hình cơ bản
        ydl_opts = {
            'outtmpl': os.path.join(DOWNLOAD_FOLDER, f"{file_id}.%(ext)s"),
            'noplaylist': True,
            'logger': SocketLogger(),
            'writethumbnail': True,   # Tải ảnh bìa
            'addmetadata': True,      # Gắn thông tin tác giả, tiêu đề vào file
            'progress_hooks': [lambda d: socketio.emit('log_update', {'data': f"Tiến độ: {d.get('_percent_str', '0%')} - Tốc độ: {d.get('_speed_str', 'N/A')}"}) if d['status'] == 'downloading' else None],
        }

        if format_type == 'mp3':
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [
                    {'key': 'FFmpegExtractAudio','preferredcodec': 'mp3','preferredquality': '192'},
                    {'key': 'FFmpegMetadata'}, # Gắn metadata cho MP3
                    {'key': 'EmbedThumbnail'}, # Gắn ảnh bìa vào file MP3
                ],
            })
        else: # Video MP4
            # Logic chọn độ phân giải
            if quality == 'best':
                format_str = 'bestvideo+bestaudio/best'
            else:
                # Tải video có chiều cao <= quality (vd: 1080) và ghép với audio tốt nhất
                format_str = f"bestvideo[height<={quality}]+bestaudio/best[height<={quality}]"

            ydl_opts.update({
                'format': format_str,
                'merge_output_format': 'mp4',
                'postprocessors': [
                    {'key': 'FFmpegMetadata'}, # Gắn metadata cho MP4
                    {'key': 'EmbedThumbnail'}, # Gắn ảnh bìa vào file MP4 (Một số player có thể không hiện)
                ],
            })

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            socketio.emit('log_update', {'data': 'Đang phân tích và xử lý metadata...'})
            info = ydl.extract_info(url, download=True)
            
            # Lấy tên file gốc
            real_title = info.get('title', 'video')
            real_title = "".join([c for c in real_title if c.isalpha() or c.isdigit() or c in " .-_()[]"]).strip()
            
            ext = 'mp3' if format_type == 'mp3' else 'mp4'
            saved_filename = f"{file_id}.{ext}"
            user_filename = f"{real_title}.{ext}"

            socketio.emit('download_complete', {
                'file_id': saved_filename,
                'user_filename': user_filename
            })

    except Exception as e:
        socketio.emit('log_update', {'data': f"LỖI: {str(e)}"})
        socketio.emit('download_error')

@socketio.on('start_download')
def handle_download(data):
    thread = threading.Thread(target=process_download, args=(data['url'], data['format'], data['quality']))
    thread.start()

def secure_delete(file_path):
    time.sleep(2)
    for i in range(5):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"[DỌN DẸP] Đã xóa: {os.path.basename(file_path)}")
                return
        except:
            time.sleep(2)

@app.route('/get_file/<file_id>')
def get_file(file_id):
    user_filename = request.args.get('name', 'video.mp4')
    file_path = os.path.join(DOWNLOAD_FOLDER, file_id)
    
    @after_this_request
    def remove_file(response):
        threading.Thread(target=secure_delete, args=(file_path,)).start()
        return response

    return send_file(file_path, as_attachment=True, download_name=user_filename)

if __name__ == '__main__':
    socketio.run(app, debug=True, port=5000)