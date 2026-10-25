// Optional managed-preview launcher. Normal users run python app.py.
import { spawn } from 'node:child_process';
const python = process.env.CODEX_PRIMARY_RUNTIME_PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const child = spawn(python, ['app.py'], {stdio:'inherit', env:{...process.env,HOST:'0.0.0.0',PORT:'4173'}});
child.on('exit', code => process.exit(code ?? 1));
process.on('SIGTERM', () => child.kill('SIGTERM'));
