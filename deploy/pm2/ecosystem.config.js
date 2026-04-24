// PM2 Ecosystem File — kpopjournal.tokyo Next.js
// Destination: /home/kpopjournal-frontend/ecosystem.config.js
// Start:       cd /home/kpopjournal-frontend && pm2 start ecosystem.config.js
// Save:        pm2 save

module.exports = {
  apps: [
    {
      name: "kpopjournal",
      script: "npm",
      args: "start",
      cwd: "/home/kpopjournal-frontend",
      instances: 2,
      exec_mode: "cluster",
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "production",
        PORT: 3000,
      },
      // Graceful restart
      kill_timeout: 5000,
      listen_timeout: 10000,
      // Auto-restart on crash
      autorestart: true,
      max_restarts: 10,
      restart_delay: 1000,
      // Logging
      log_date_format: "YYYY-MM-DD HH:mm:ss Z",
      error_file: "/home/kpopjournal-frontend/logs/pm2-error.log",
      out_file: "/home/kpopjournal-frontend/logs/pm2-out.log",
      merge_logs: true,
      // Watch (disabled in production)
      watch: false,
    },
  ],
};
