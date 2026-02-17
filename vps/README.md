# VPS WhatsApp OTP Server

WPPConnect server deployed on the org's Ubuntu VPS for sending WhatsApp OTPs.

## Setup

### 1. Install Docker

```bash
sudo apt update && sudo apt install -y docker.io docker-compose
sudo systemctl enable docker && sudo systemctl start docker
```

### 2. Deploy

```bash
cd /opt/wpp-otp-server   # or wherever you clone this
cp config.ts config.ts    # edit secretKey in config.ts first!
docker-compose up -d
```

### 3. Change the Secret Key

Edit `config.ts` and replace `MY_STRONG_SECRET_KEY_CHANGE_ME` with a strong random string. This same value goes into the Next.js app's `WHATSAPP_OTP_SECRET` env var.

### 4. Link WhatsApp via QR Code

1. Open `http://<VPS_IP>:21465/api/hospital/start-session` (POST) to create the session
2. Call `http://<VPS_IP>:21465/api/hospital/qrcode-session` (GET) to get the QR
3. Scan the QR with the hospital's WhatsApp number
4. Session is now linked and will auto-reconnect

### 5. Firewall

Only allow port 21465 from your Next.js server IP:

```bash
sudo ufw allow from <NEXTJS_SERVER_IP> to any port 21465
sudo ufw enable
```

## Environment Variables (Next.js side)

Add these to `.env.local`:

```
WHATSAPP_OTP_URL=http://<VPS_IP>:21465
WHATSAPP_OTP_SECRET=<same-secret-as-config.ts>
WHATSAPP_OTP_SESSION=hospital
```

## Verify

```bash
# Check container is running
docker-compose ps

# Check logs
docker-compose logs -f wppconnect
```
