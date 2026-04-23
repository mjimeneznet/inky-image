# Inky Image Viewer

Inky Image Viewer is a Python service for Raspberry Pi that shows images on an Inky e-ink display,
supports hardware button control (A/B/C/D), and provides a minimal web UI for folder management.

## Features

- Button A: start/stop slideshow
- Button B: next image
- Button C: previous image
- Button D: cycle slideshow source mode (`directory` -> `image_list` -> `url` -> `upload`)
- Upload mode from browser/mobile (file upload)
- Web UI to add/remove/activate directories
- Web UI image list mode with individually selected images across directories
- Persistent JSON configuration
- systemd service deployment for Debian

## Project Structure

```text
inky-image/
├── inky_image/
│   ├── main.py
│   ├── config.py
│   ├── display.py
│   ├── image_manager.py
│   ├── button_handler.py
│   ├── slideshow.py
│   └── web_app.py
├── templates/index.html
├── static/style.css
├── requirements.txt
├── inky-image.service
└── install.sh
```

## Requirements

- Raspberry Pi running Debian
- Inky e-ink display (Inky Impression compatible)
- Python 3.9+
- Root access for GPIO/SPI and systemd service setup

## Installation

1. Clone the repository on your Raspberry Pi.
2. Run the installer:

```bash
git clone <your-repository-url> inky-image
cd inky-image
sudo chmod +x install.sh
sudo ./install.sh
```

The installer will:

- Install system dependencies
- Copy files to `/home/<user>/inky-image`
- Create a virtual environment
- Install Python dependencies
- Install and start `inky-image.service`

## Usage

### Web UI

- Open `http://<raspberry-pi-ip>`
- Add one or more image directories
- Activate a directory for playback
- Use controls for next/previous/toggle slideshow

### Hardware Buttons

- A -> Toggle slideshow
- B -> Next image
- C -> Previous image
- D -> Next source mode (`directory` -> `image_list` -> `url` -> `upload`)

## Configuration

Default config path:

`/home/<user>/.config/inky-image/config.json`

Stored values include:

- `directories`
- `active_directory_index`
- `selected_images`
- `uploaded_images`
- `slideshow_mode`
- `current_image_index`
- `slideshow_interval`
- `slideshow_running`
- `saturation`
- `render_width`
- `render_height`
- `web_port`

## Service Management

```bash
sudo systemctl status inky-image.service
sudo systemctl restart inky-image.service
sudo journalctl -u inky-image.service -f
```

## Troubleshooting

- If buttons do not work, verify GPIO mapping and run `gpioinfo`.
- If display does not update, confirm SPI is enabled on the Raspberry Pi.
- If the service fails, check logs with:
  `sudo journalctl -u inky-image.service --no-pager`.
- Ensure configured directories exist and contain supported image files.

