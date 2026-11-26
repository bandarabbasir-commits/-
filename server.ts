import 'dotenv/config';
import express from 'express';
import http from 'node:http';
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawn, execFileSync, execSync, type ChildProcess } from 'node:child_process';
import httpProxy from 'http-proxy';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const PORT = Number(process.env.PORT || 3000);
const FASTAPI_HOST = '127.0.0.1';
const FASTAPI_PORT = Number(process.env.FASTAPI_PORT || 8001);
const FASTAPI_TARGET = `http://${FASTAPI_HOST}:${FASTAPI_PORT}`;
const IS_PROD = process.env.NODE_ENV === 'production';

let uvicornProc: ChildProcess | null = null;
let backendReady = false;
let backendBooting = false;
let backendBootError: string | null = null;
let isShuttingDown = false;
let restartTimer: NodeJS.Timeout | null = null;

function isRootUser(): boolean {
  return typeof process.getuid === 'function' && process.getuid() === 0;
}

function shellQuote(val: string): string {
  return `'${val.replace(/'/g, `'\\''`)}'`;
}

function isDirWritable(dirPath: string): boolean {
  try {
    fs.accessSync(dirPath, fs.constants.W_OK);
    return true;
  } catch {
    return false;
  }
}

function checkTcpPort(host: string, port: number, timeoutMs = 1000): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    let settled = false;
    const done = (ok: boolean) => {
      if (!settled) {
        settled = true;
        socket.destroy();
        resolve(ok);
      }
    };
    socket.setTimeout(timeoutMs);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
    socket.connect(port, host);
  });
}

function parsePgUrl(rawUrl: string): {
  host: string;
  port: number;
  user: string;
  password: string;
  database: string;
} {
  try {
    const normalized = rawUrl.replace(/^postgresql\+asyncpg:\/\//, 'postgresql://');
    const u = new URL(normalized);
    return {
      host: u.hostname || '127.0.0.1',
      port: Number(u.port || 5432),
      user: decodeURIComponent(u.username || 'hb_app'),
      password: decodeURIComponent(u.password || 'hb_dev_password'),
      database: decodeURIComponent((u.pathname || '/hormozgan_bidar').replace(/^\//, '')) || 'hormozgan_bidar',
    };
  } catch {
    return {
      host: '127.0.0.1',
      port: 5432,
      user: 'hb_app',
      password: 'hb_dev_password',
      database: 'hormozgan_bidar',
    };
  }
}

function findPgBinary(binName: string): { binPath: string; ldPath: string } | null {
  const candidates: Array<{ dir: string; ld: string }> = [
    { dir: '/usr/lib/postgresql/15/bin', ld: process.env.LD_LIBRARY_PATH || '' },
    {
      dir: '/opt/pg15/usr/lib/postgresql/15/bin',
      ld: `/opt/pg15/usr/lib/x86_64-linux-gnu:/opt/pg15/lib/x86_64-linux-gnu:${process.env.LD_LIBRARY_PATH || ''}`,
    },
    {
      dir: '/tmp/pg15/usr/lib/postgresql/15/bin',
      ld: `/tmp/pg15/usr/lib/x86_64-linux-gnu:/tmp/pg15/lib/x86_64-linux-gnu:${process.env.LD_LIBRARY_PATH || ''}`,
    },
  ];
  for (const c of candidates) {
    const full = path.join(c.dir, binName);
    if (fs.existsSync(full)) {
      return { binPath: full, ldPath: c.ld };
    }
  }
  return null;
}

function resolvePgOwner(): string {
  try {
    const passwd = fs.readFileSync('/etc/passwd', 'utf8');
    if (passwd.includes('\npostgres:') || passwd.startsWith('postgres:')) return 'postgres';
    if (isRootUser()) {
      try {
        execSync('useradd --system --no-create-home --shell /bin/sh postgres', { stdio: 'ignore' });
        return 'postgres';
      } catch {
        // Fallback below
      }
    }
    if (passwd.includes('\nappuser:') || passwd.startsWith('appuser:')) return 'appuser';
    if (passwd.includes('\nnobody:') || passwd.startsWith('nobody:')) return 'nobody';
  } catch {
    // Ignore
  }
  return 'postgres';
}

function installOsPackages(packages: string[]): boolean {
  if (!isRootUser()) {
    console.warn(`[server] Cannot apt-get install [${packages.join(', ')}] without root privileges.`);
    return false;
  }
  try {
    console.log(`[server] Installing missing OS packages: ${packages.join(' ')}...`);
    execSync(
      `DEBIAN_FRONTEND=noninteractive apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends ${packages.join(' ')} && rm -rf /var/lib/apt/lists/*`,
      { stdio: 'inherit' }
    );
    return true;
  } catch (err) {
    console.error('[server] Failed to install OS packages:', err);
    return false;
  }
}

function extractPostgresPackages(): boolean {
  if (!isRootUser()) {
    console.warn('[server] Cannot download PostgreSQL 15 packages without root privileges.');
    return false;
  }
  const targetRoot = isDirWritable('/opt') ? '/opt/pg15' : '/tmp/pg15';
  const debDir = '/tmp/pg-debs';
  try {
    console.log(`[server] Downloading & extracting PostgreSQL 15 binaries into ${targetRoot}...`);
    fs.mkdirSync(debDir, { recursive: true });
    fs.mkdirSync(targetRoot, { recursive: true });
    execSync(
      `DEBIAN_FRONTEND=noninteractive apt-get update -qq && rm -f ${debDir}/*.deb && DEBIAN_FRONTEND=noninteractive apt-get -o Dir::Cache::archives=${shellQuote(debDir)} -d install -y -qq --no-install-recommends postgresql-15 postgresql-client-15 && for f in ${debDir}/*.deb; do dpkg -x "$f" ${shellQuote(targetRoot)}; done && rm -rf ${debDir} /var/lib/apt/lists/*`,
      { stdio: 'inherit' }
    );
    return fs.existsSync(path.join(targetRoot, 'usr/lib/postgresql/15/bin/pg_ctl'));
  } catch (err) {
    console.error('[server] Failed to extract PostgreSQL 15 packages:', err);
    return false;
  }
}

async function ensureLocalPostgresRunning(appDbUrl: string, adminDbUrl: string): Promise<void> {
  const appCfg = parsePgUrl(appDbUrl);
  const adminCfg = parsePgUrl(adminDbUrl);

  const isLocalHost = appCfg.host === '127.0.0.1' || appCfg.host === 'localhost';
  if (!isLocalHost) {
    return;
  }

  let pgCtlInfo = findPgBinary('pg_ctl');
  let initDbInfo = findPgBinary('initdb');
  let psqlInfo = findPgBinary('psql');

  if (!pgCtlInfo || !initDbInfo || !psqlInfo) {
    extractPostgresPackages();
    pgCtlInfo = findPgBinary('pg_ctl');
    initDbInfo = findPgBinary('initdb');
    psqlInfo = findPgBinary('psql');
  }

  const alreadyListening = await checkTcpPort('127.0.0.1', appCfg.port, 800);
  if (alreadyListening) {
    if (psqlInfo) {
      await ensurePgDatabaseAndRoles(psqlInfo, appCfg, adminCfg);
    }
    return;
  }

  if (!pgCtlInfo || !initDbInfo || !psqlInfo) {
    throw new Error('PostgreSQL 15 binaries (pg_ctl/initdb/psql) are missing.');
  }

  const useAppDirs = fs.existsSync('/app') && isDirWritable('/app');
  const pgDataDir = useAppDirs ? '/app/pgdata' : '/tmp/hb_pgdata';
  const pgRunDir = useAppDirs ? '/app/pgrun' : '/tmp/hb_pgrun';
  const pgOwner = resolvePgOwner();

  fs.mkdirSync(pgDataDir, { recursive: true });
  fs.mkdirSync(pgRunDir, { recursive: true });
  if (isRootUser()) {
    execSync(`chown -R ${pgOwner}:${pgOwner} ${shellQuote(pgDataDir)} ${shellQuote(pgRunDir)}`);
    execSync(`chmod 700 ${shellQuote(pgDataDir)}`);
  }

  const runAsPgOwner = (cmd: string, inheritIo = false) => {
    const wrapped = pgCtlInfo!.ldPath ? `LD_LIBRARY_PATH=${shellQuote(pgCtlInfo!.ldPath)} ${cmd}` : cmd;
    if (isRootUser()) {
      execSync(`su -s /bin/sh ${pgOwner} -c ${shellQuote(wrapped)}`, {
        stdio: inheritIo ? 'inherit' : 'pipe',
      });
    } else {
      execSync(wrapped, { stdio: inheritIo ? 'inherit' : 'pipe' });
    }
  };

  if (!fs.existsSync(path.join(pgDataDir, 'PG_VERSION'))) {
    console.log(`[server] Initializing PostgreSQL 15 data cluster at ${pgDataDir}...`);
    runAsPgOwner(
      `${shellQuote(initDbInfo.binPath)} -D ${shellQuote(pgDataDir)} -E UTF8 --locale=C.UTF-8 -A trust`,
      false
    );
  }

  let running = false;
  try {
    runAsPgOwner(`${shellQuote(pgCtlInfo.binPath)} -D ${shellQuote(pgDataDir)} status`);
    running = true;
  } catch {
    running = false;
  }

  if (!running) {
    const pidFile = path.join(pgDataDir, 'postmaster.pid');
    if (fs.existsSync(pidFile)) {
      try {
        fs.unlinkSync(pidFile);
      } catch {
        // Ignore
      }
    }
    console.log('[server] Starting local PostgreSQL 15 instance...');
    runAsPgOwner(
      `${shellQuote(pgCtlInfo.binPath)} -D ${shellQuote(pgDataDir)} -l /tmp/postgres.log -o ${shellQuote(`-k ${pgRunDir} -h 127.0.0.1 -p ${appCfg.port}`)} start`,
      false
    );
  }

  await ensurePgDatabaseAndRoles(psqlInfo, appCfg, adminCfg, pgRunDir);
}

async function ensurePgDatabaseAndRoles(
  psqlInfo: { binPath: string; ldPath: string },
  appCfg: ReturnType<typeof parsePgUrl>,
  adminCfg: ReturnType<typeof parsePgUrl>,
  pgRunDir?: string
): Promise<void> {
  const pgOwner = resolvePgOwner();
  const hostArg = pgRunDir ? `-h ${shellQuote(pgRunDir)} -p ${appCfg.port}` : `-h 127.0.0.1 -p ${appCfg.port}`;
  const runPsql = (dbName: string, sql: string) => {
    const cmd = `${psqlInfo.ldPath ? `LD_LIBRARY_PATH=${shellQuote(psqlInfo.ldPath)} ` : ''}${shellQuote(psqlInfo.binPath)} ${hostArg} -U ${shellQuote(pgOwner)} -d ${shellQuote(dbName)} -v ON_ERROR_STOP=1 -c ${shellQuote(sql)}`;
    if (isRootUser()) {
      execSync(`su -s /bin/sh ${pgOwner} -c ${shellQuote(cmd)}`, { stdio: 'pipe' });
    } else {
      execSync(cmd, { stdio: 'pipe' });
    }
  };

  const escapeLit = (v: string) => v.replace(/'/g, "''");
  const escapeIdent = (v: string) => `"${v.replace(/"/g, '""')}"`;

  try {
    runPsql(
      'postgres',
      `DO $$
      BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${escapeLit(adminCfg.user)}') THEN
          CREATE ROLE ${escapeIdent(adminCfg.user)} WITH LOGIN SUPERUSER CREATEDB CREATEROLE PASSWORD '${escapeLit(adminCfg.password)}';
        ELSE
          ALTER ROLE ${escapeIdent(adminCfg.user)} WITH LOGIN SUPERUSER PASSWORD '${escapeLit(adminCfg.password)}';
        END IF;
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${escapeLit(appCfg.user)}') THEN
          CREATE ROLE ${escapeIdent(appCfg.user)} WITH LOGIN PASSWORD '${escapeLit(appCfg.password)}';
        ELSE
          ALTER ROLE ${escapeIdent(appCfg.user)} WITH LOGIN PASSWORD '${escapeLit(appCfg.password)}';
        END IF;
      END $$;`
    );

    const dbCheckCmd = `${psqlInfo.ldPath ? `LD_LIBRARY_PATH=${shellQuote(psqlInfo.ldPath)} ` : ''}${shellQuote(psqlInfo.binPath)} ${hostArg} -U ${shellQuote(pgOwner)} -d postgres -tAc ${shellQuote(`SELECT 1 FROM pg_database WHERE datname='${escapeLit(appCfg.database)}'`)}`;
    const existsOut = isRootUser()
      ? execSync(`su -s /bin/sh ${pgOwner} -c ${shellQuote(dbCheckCmd)}`, { encoding: 'utf8' }).trim()
      : execSync(dbCheckCmd, { encoding: 'utf8' }).trim();

    if (existsOut !== '1') {
      runPsql(
        'postgres',
        `CREATE DATABASE ${escapeIdent(appCfg.database)} OWNER ${escapeIdent(adminCfg.user)} ENCODING 'UTF8';`
      );
    }

    runPsql(
      appCfg.database,
      `CREATE EXTENSION IF NOT EXISTS pg_trgm;
       GRANT USAGE, CREATE ON SCHEMA public TO ${escapeIdent(adminCfg.user)};
       GRANT USAGE ON SCHEMA public TO ${escapeIdent(appCfg.user)};`
    );
  } catch (err) {
    console.warn('[server] PostgreSQL role/database ensure warning:', err instanceof Error ? err.message : err);
  }
}

function testPythonPackages(pythonExe: string): boolean {
  try {
    execFileSync(
      pythonExe,
      [
        '-c',
        'import fastapi, uvicorn, sqlalchemy, asyncpg, alembic, pydantic_settings, argon2, jdatetime, docx, openpyxl, multipart',
      ],
      { stdio: 'pipe', timeout: 8000 }
    );
    return true;
  } catch {
    return false;
  }
}

function ensurePythonRuntime(backendDir: string): string {
  const candidates = [
    path.join(backendDir, '.venv', 'bin', 'python3'),
    path.join(backendDir, '.venv', 'bin', 'python'),
    '/tmp/hb-venv/bin/python3',
    'python3',
  ];

  for (const cand of candidates) {
    if (cand === 'python3' || fs.existsSync(cand)) {
      if (testPythonPackages(cand)) {
        return cand;
      }
    }
  }

  // Need to create a clean virtualenv and install backend/requirements.txt
  let canVenv = false;
  try {
    execFileSync('python3', ['-c', 'import ensurepip, venv'], { stdio: 'pipe' });
    canVenv = true;
  } catch {
    canVenv = false;
  }

  if (!canVenv) {
    installOsPackages(['python3-venv', 'python3-pip']);
  }

  const targetVenvDir = !IS_PROD && isDirWritable(backendDir) ? path.join(backendDir, '.venv') : '/tmp/hb-venv';
  const venvPython = path.join(targetVenvDir, 'bin', 'python3');

  console.log(`[server] Creating Python virtualenv at ${targetVenvDir} and installing dependencies...`);
  if (!fs.existsSync(venvPython)) {
    execFileSync('python3', ['-m', 'venv', targetVenvDir], { stdio: 'inherit' });
  }
  execFileSync(venvPython, ['-m', 'pip', 'install', '--no-cache-dir', '-r', 'requirements.txt'], {
    cwd: backendDir,
    stdio: 'inherit',
  });

  if (!testPythonPackages(venvPython)) {
    throw new Error('Python dependencies could not be verified after pip install.');
  }
  return venvPython;
}

function resolveProductionSecretKey(): string {
  const existing = (process.env.SECRET_KEY || '').trim();
  if (existing.length >= 32) {
    return existing;
  }
  const secretFile = '/tmp/.hb_secret_key';
  if (fs.existsSync(secretFile)) {
    const saved = fs.readFileSync(secretFile, 'utf8').trim();
    if (saved.length >= 32) return saved;
  }
  const generated = crypto.randomBytes(32).toString('hex');
  try {
    fs.writeFileSync(secretFile, generated, { mode: 0o600 });
  } catch {
    // Non-fatal; stays in memory for this process
  }
  return generated;
}

function buildBackendEnv(): NodeJS.ProcessEnv {
  const databaseUrl =
    process.env.DATABASE_URL || 'postgresql+asyncpg://hb_app:hb_dev_password@127.0.0.1:5432/hormozgan_bidar';
  const databaseAdminUrl =
    process.env.DATABASE_ADMIN_URL || 'postgresql+asyncpg://hb_admin:hb_dev_password@127.0.0.1:5432/hormozgan_bidar';

  const origins = [
    process.env.ALLOWED_ORIGINS || '',
    `http://localhost:${PORT}`,
    `http://127.0.0.1:${PORT}`,
    'http://localhost:3000',
    'http://127.0.0.1:3000',
    process.env.APP_URL || '',
  ]
    .join(',')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);

  return {
    ...process.env,
    PYTHONUNBUFFERED: '1',
    APP_ENV: process.env.APP_ENV || (IS_PROD ? 'production' : 'development'),
    DATABASE_URL: databaseUrl,
    DATABASE_ADMIN_URL: databaseAdminUrl,
    SECRET_KEY: IS_PROD ? resolveProductionSecretKey() : process.env.SECRET_KEY || 'local-ephemeral-dev-key-not-for-prod-9f8e7d6c5b4a3210',
    COOKIE_SECURE: process.env.COOKIE_SECURE || (IS_PROD ? 'true' : 'false'),
    DEMO_SEED_ENABLED: process.env.DEMO_SEED_ENABLED || (IS_PROD ? 'false' : 'true'),
    ALLOWED_ORIGINS: Array.from(new Set(origins)).join(','),
  };
}

function runMigrationsAndSeed(pythonExe: string, backendDir: string, apiEnv: NodeJS.ProcessEnv): void {
  console.log('[server] Running Alembic migrations...');
  execFileSync(pythonExe, ['-m', 'alembic', 'upgrade', 'head'], {
    cwd: backendDir,
    env: {
      ...apiEnv,
      DATABASE_URL: apiEnv.DATABASE_ADMIN_URL || apiEnv.DATABASE_URL,
    },
    stdio: 'inherit',
  });

  if (apiEnv.APP_ENV !== 'production' && apiEnv.DEMO_SEED_ENABLED === 'true') {
    console.log('[server] Ensuring demo dataset...');
    execFileSync(pythonExe, ['-m', 'app.seed', '--mode', 'demo'], {
      cwd: backendDir,
      env: apiEnv,
      stdio: 'inherit',
    });
  } else if (apiEnv.APP_ENV === 'production' && apiEnv.ADMIN_INITIAL_PASSWORD) {
    console.log('[server] Ensuring production initial admin...');
    execFileSync(pythonExe, ['-m', 'app.seed', '--mode', 'prod'], {
      cwd: backendDir,
      env: apiEnv,
      stdio: 'inherit',
    });
  }
}

async function waitForFastApi(timeoutMs: number): Promise<boolean> {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    try {
      const res = await fetch(`${FASTAPI_TARGET}/api/v1/health`);
      if (res.ok) {
        backendReady = true;
        console.log(`[server] FastAPI backend is ready on ${FASTAPI_TARGET}.`);
        return true;
      }
    } catch {
      // Keep polling until uvicorn listens
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  return false;
}

function scheduleRestart() {
  if (isShuttingDown || restartTimer) return;
  restartTimer = setTimeout(() => {
    restartTimer = null;
    if (!isShuttingDown) {
      console.log('[server] Restarting FastAPI backend...');
      void startBackendLifecycle();
    }
  }, 2500);
}

function spawnUvicorn(pythonExe: string, backendDir: string, apiEnv: NodeJS.ProcessEnv): void {
  if (uvicornProc && uvicornProc.exitCode === null && !uvicornProc.killed) {
    return;
  }
  uvicornProc = spawn(
    pythonExe,
    [
      '-m',
      'uvicorn',
      'app.main:app',
      '--host',
      FASTAPI_HOST,
      '--port',
      String(FASTAPI_PORT),
      '--log-level',
      'warning',
      '--proxy-headers',
      '--forwarded-allow-ips',
      '127.0.0.1',
    ],
    {
      cwd: backendDir,
      env: apiEnv,
      stdio: ['ignore', 'pipe', 'pipe'],
    }
  );

  uvicornProc.on('error', (err) => {
    backendReady = false;
    backendBootError = err.message;
    console.error('[api] Failed to spawn FastAPI process:', err.message);
    scheduleRestart();
  });

  uvicornProc.stdout?.on('data', (d) => process.stdout.write(`[api] ${d}`));
  uvicornProc.stderr?.on('data', (d) => process.stderr.write(`[api] ${d}`));
  uvicornProc.on('exit', (code, signal) => {
    backendReady = false;
    uvicornProc = null;
    console.warn(`[api] FastAPI exited (code=${code}, signal=${signal})`);
    scheduleRestart();
  });
}

let activeBootstrapPromise: Promise<void> | null = null;

async function startBackendLifecycle(): Promise<void> {
  if (activeBootstrapPromise) return activeBootstrapPromise;
  backendBooting = true;
  backendBootError = null;

  activeBootstrapPromise = (async () => {
    try {
      const backendDir = path.join(__dirname, 'backend');
      const apiEnv = buildBackendEnv();

      await ensureLocalPostgresRunning(apiEnv.DATABASE_URL!, apiEnv.DATABASE_ADMIN_URL!);
      const pythonExe = ensurePythonRuntime(backendDir);
      runMigrationsAndSeed(pythonExe, backendDir, apiEnv);

      spawnUvicorn(pythonExe, backendDir, apiEnv);
      const ok = await waitForFastApi(25000);
      if (!ok) {
        console.warn('[server] FastAPI health check timed out; will continue waiting on requests.');
      }
    } catch (err) {
      backendReady = false;
      backendBootError = err instanceof Error ? err.message : String(err);
      console.error('[server] Backend bootstrap error (HTTP server remains live):', backendBootError);
      scheduleRestart();
    } finally {
      backendBooting = false;
      activeBootstrapPromise = null;
    }
  })();

  return activeBootstrapPromise;
}

async function waitForBackendReadyUpTo(ms: number): Promise<boolean> {
  if (backendReady) return true;
  const p = activeBootstrapPromise || startBackendLifecycle();
  await Promise.race([p, new Promise((r) => setTimeout(r, ms))]);
  return backendReady;
}

async function bootstrap() {
  const app = express();
  app.disable('x-powered-by');

  const proxy = httpProxy.createProxyServer({
    target: FASTAPI_TARGET,
    ws: true,
    changeOrigin: false,
    xfwd: false,
  });

  proxy.on('error', (err, _req, res) => {
    console.error('[proxy] Error forwarding to FastAPI:', err.message);
    if (res && 'writeHead' in res && !res.headersSent) {
      (res as http.ServerResponse).writeHead(503, { 'Content-Type': 'application/json; charset=utf-8' });
      (res as http.ServerResponse).end(
        JSON.stringify({ detail: 'سرور پردازش درخواست در حال راه‌اندازی است. لحظاتی بعد دوباره تلاش کنید.' })
      );
    }
  });

  // Proxy all /api requests directly (unparsed body stream) to FastAPI
  app.use('/api', async (req, res) => {
    if (!backendReady) {
      await waitForBackendReadyUpTo(15000);
    }
    if (!backendReady) {
      res.status(503).json({
        detail: backendBooting
          ? 'سرور در حال آماده‌سازی پایگاه‌داده و سرویس‌ها است؛ لطفاً چند لحظه بعد تلاش کنید.'
          : `خطا در راه‌اندازی سرویس داخلی: ${backendBootError || 'نامشخص'}`,
      });
      return;
    }
    req.url = `/api${req.url}`;
    proxy.web(req, res, { target: FASTAPI_TARGET });
  });

  if (!IS_PROD) {
    const { createServer: createViteServer } = await import('vite');
    const vite = await createViteServer({
      server: {
        middlewareMode: true,
        hmr: false,
        allowedHosts: true,
      },
      appType: 'spa',
    });
    app.use(vite.middlewares);
  } else {
    const distDir = path.join(__dirname, 'dist');
    app.use(express.static(distDir, { index: false }));
    app.get('*', (req, res) => {
      if (req.path.startsWith('/api')) {
        res.status(404).json({ detail: 'یافت نشد' });
        return;
      }
      res.sendFile(path.join(distDir, 'index.html'));
    });
  }

  const server = http.createServer(app);

  // Proxy WebSocket upgrades (/api/v1/ws) preserving Origin and Cookie headers
  server.on('upgrade', async (req, socket, head) => {
    if (req.url?.startsWith('/api/')) {
      if (!backendReady) {
        await waitForBackendReadyUpTo(10000);
      }
      if (!backendReady) {
        socket.destroy();
        return;
      }
      proxy.ws(req, socket, head, { target: FASTAPI_TARGET });
    } else {
      socket.destroy();
    }
  });

  const shutdown = () => {
    isShuttingDown = true;
    if (restartTimer) clearTimeout(restartTimer);
    if (uvicornProc && !uvicornProc.killed) {
      uvicornProc.kill('SIGTERM');
    }
    server.close(() => process.exit(0));
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  // Listen immediately so Cloud Run and dev health probes succeed right away
  server.listen(PORT, '0.0.0.0', () => {
    console.log(`[server] Hormozgan Bidar v2 listening on http://0.0.0.0:${PORT} (${IS_PROD ? 'prod' : 'dev'})`);
    void startBackendLifecycle();
  });
}

bootstrap().catch((err) => {
  console.error('[server] Fatal startup error:', err);
  process.exit(1);
});
