const wppconnect = require("@wppconnect-team/wppconnect");
const express = require("express");

const app = express();
app.use(express.json());

let client = null;

// Start WPPConnect — QR shows in terminal (pm2 logs)
wppconnect
  .create({
    session: "hospital",
    catchQR: (base64Qr, asciiQR) => {
      console.log("\n\n========== SCAN THIS QR CODE ==========\n");
      console.log(asciiQR);
      console.log("\n========================================\n");
    },
    statusFind: (status) => {
      console.log("Status:", status);
    },
    headless: true,
    logQR: true,
    puppeteerOptions: {
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    },
  })
  .then((c) => {
    client = c;
    console.log("\n✅ WhatsApp connected!\n");
  })
  .catch((err) => {
    console.error("Failed to start:", err);
  });

// Dead simple send endpoint — no auth, no tokens
app.post("/send", async (req, res) => {
  const { phone, message } = req.body;

  if (!client) {
    return res.status(503).json({ error: "WhatsApp not connected yet" });
  }

  try {
    await client.sendText(`${phone}@c.us`, message);
    res.json({ success: true });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

app.get("/status", (req, res) => {
  res.json({ connected: !!client });
});

app.listen(3001, () => {
  console.log("OTP server running on port 3001");
});
