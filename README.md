# 🪐 Universal Media Downloader

A powerful, high-performance web-based media downloader supporting **YouTube, Facebook, Twitter (X), Instagram, Reddit, TikTok**, and 1,000+ other sites. 

Built with a modern "Cyberpunk" interface using **Python (Flask)**, **Socket.IO** for real-time progress tracking, and the robust **yt-dlp** engine.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.8+-yellow.svg)
![Status](https://img.shields.io/badge/status-active-success.svg)

## ✨ Key Features

* **🌍 Multi-Platform Support:** Downloads videos/audio from YouTube, Facebook, Instagram, Twitter, TikTok, Reddit, Vimeo, and more.
* **⚡ Real-time Progress:** Websocket integration displays download speed, file size, and percentage in real-time (no page reload).
* **🎬 Smart Quality Selection:** Automatically detects and lets users choose resolutions (4K, 2K, 1080p, 720p).
* **🎵 Metadata Embedding:** Automatically adds cover art (thumbnail), artist, and title to MP3/MP4 files for a complete media experience.
* **🧹 Auto-Cleanup:** Server automatically deletes temporary files immediately after the user downloads them to ensure privacy and save storage.
* **💎 Modern UI:** Responsive Dark Mode / Cyberpunk interface with live video preview before downloading.

## 📸 Screenshots

![App Dashboard](https://via.placeholder.com/800x450?text=Universal+Downloader+Dashboard)

## 🛠️ Tech Stack

* **Backend:** Python, Flask, Flask-SocketIO
* **Core Engine:** yt-dlp (The most advanced media downloader tool)
* **Frontend:** HTML5, CSS3 (Custom Dark Theme), JavaScript (Socket.io-client)
* **Processing:** FFmpeg (Required for high-quality video merging and audio conversion)

## 🚀 Installation & Setup

### Prerequisites
1.  **Python** (v3.8 or higher)
2.  **FFmpeg** (Must be installed and added to system PATH)

### Steps

1.  **Clone the repository**
    ```bash
    git clone [https://github.com/YOUR_USERNAME/universal-media-downloader.git](https://github.com/YOUR_USERNAME/universal-media-downloader.git)
    cd universal-media-downloader
    ```

2.  **Install dependencies**
    Create a `requirements.txt` file and install:
    ```bash
    pip install -r requirements.txt
    ```

3.  **Run the application**
    ```bash
    python app.py
    ```

4.  **Access the tool**
    Open your browser and navigate to: `http://127.0.0.1:5000`

## 📝 Usage

1.  **Paste a URL** from any supported site (e.g., a YouTube video, a Facebook reel, a Twitter post).
2.  Click **"🔍 Quét Video" (Scan)** to fetch metadata.
3.  Select your desired **Format** (MP4/MP3) and **Quality**.
4.  Click **"⬇️ DOWNLOAD"**. The server will process the file and send it to your device instantly.

## 🤝 Contributing

Contributions are welcome! If you want to add features or fix bugs, please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License.