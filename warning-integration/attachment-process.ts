import { execFile } from 'node:child_process';

const parser = `
  import { attachmentText } from './server/pipeline.ts';
  console.log = (...values) => console.warn(...values);
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  try {
    const text = await attachmentText(Buffer.concat(chunks), process.argv[1]);
    process.stdout.write(JSON.stringify({ text }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ error: error instanceof Error ? error.message : '附件解析失败' }));
  }
`;

export function parseAttachmentInProcess(buffer: Buffer, url: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = execFile(process.execPath, [
      '--max-old-space-size=384', '--import', 'tsx', '--input-type=module', '-e', parser, url,
    ], { timeout: 45_000, maxBuffer: 1_500_000, killSignal: 'SIGKILL' }, (error, stdout) => {
      if (error) {
        reject(new Error('附件解析超出内存、时间或输出限制，需人工核查'));
        return;
      }
      try {
        const result = JSON.parse(stdout);
        if (typeof result.text !== 'string') throw new Error(result.error || '附件解析失败');
        resolve(result.text);
      } catch (cause) {
        reject(cause);
      }
    });
    child.stdin?.on('error', () => {});
    child.stdin?.end(buffer);
  });
}
