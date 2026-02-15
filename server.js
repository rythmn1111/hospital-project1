const { initServer } = require("@wppconnect/server");

initServer({
  port: 21465,
  host: "0.0.0.0",
  maxFileSize: 50,
  secretKey: "THISISMYSECURETOKEN",
  startAllSession: false,
  tokenStoreType: "file",
  cors: {
    origin: ["http://localhost:3000"],
    methods: ["GET", "POST", "PUT", "DELETE"],
  },
});
