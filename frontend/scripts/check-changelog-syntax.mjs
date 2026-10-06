/** Parse the release page before a broken quote reaches the full build. */
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const relativePath = 'frontend/src/features/about/Changelog.tsx';

function diagnose(source, label) {
  if (!source.trim()) return [`${label}: refusing an empty release page`];
  const parsed = ts.createSourceFile(label, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  return (parsed.parseDiagnostics ?? []).map((diagnostic) => {
    const { line, character } = parsed.getLineAndCharacterOfPosition(diagnostic.start ?? 0);
    return `${label}:${line + 1}:${character + 1}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, ' ')}`;
  });
}

function selfTest() {
  const cases = [
    ['valid quoted text and JSX', 'const item = "The contractor\'s claim"; export const Page = () => <p>{item}</p>;', true],
    ['escaped apostrophe', "const item = 'The contractor\\'s claim'; export const Page = () => <p>{item}</p>;", true],
    ['unescaped apostrophe', "const item = 'The contractor's claim'; export const Page = () => <p>{item}</p>;", false],
    ['missing object separator', "const item = { title: 'Release' body: 'Notes' };", false],
    ['unclosed JSX', 'export const Page = () => <section><p>Notes</section>;', false],
    ['empty input', '  \n', false],
  ];
  let failures = 0;
  for (const [label, source, shouldPass] of cases) {
    const passes = diagnose(source, label).length === 0;
    if (passes !== shouldPass) {
      console.error(`FAIL: ${label}: expected ${shouldPass ? 'acceptance' : 'refusal'}`);
      failures++;
    }
  }
  if (failures) return 1;
  console.log(`Changelog syntax self-test: ${cases.length} cases passed, including malformed TSX.`);
  return 0;
}

function main() {
  const args = process.argv.slice(2);
  if (args.length === 1 && args[0] === '--self-test') return selfTest();
  if (args.some((arg) => !['--index', '--stdin'].includes(arg)) || args.length > 1) {
    console.error('Usage: node frontend/scripts/check-changelog-syntax.mjs [--index | --stdin | --self-test]');
    return 2;
  }
  try {
    const inputs = args.includes('--stdin')
      ? [['stdin:Changelog.tsx', readFileSync(0, 'utf8')]]
      : [[relativePath, readFileSync(resolve(root, relativePath), 'utf8')]];
    if (args.includes('--index')) {
      inputs.push([`index:${relativePath}`, execFileSync('git', ['show', `:${relativePath}`], {
        cwd: root, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024,
      })]);
    }
    const failures = inputs.flatMap(([label, source]) => diagnose(source, label));
    if (failures.length) {
      failures.slice(0, 10).forEach((failure) => console.error(failure));
      if (failures.length > 10) console.error(`... ${failures.length - 10} further syntax diagnostics omitted.`);
      return 1;
    }
    console.log(`Changelog syntax: ${inputs.map(([label]) => label).join(', ')} passed.`);
    return 0;
  } catch (error) {
    console.error(`Changelog syntax could not be checked: ${error.message}`);
    return 2;
  }
}

process.exitCode = main();
