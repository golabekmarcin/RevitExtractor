import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const launcher = fileURLToPath(new URL('../public/downloads/Start-RevitExport.ps1', import.meta.url));
const shell = process.platform === 'win32' ? 'powershell.exe' : 'pwsh';
const available = spawnSync(shell, ['-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()'], { encoding: 'utf8' }).status === 0;
const quote = value => `'${value.replaceAll("'", "''")}'`;

test('launcher defaults, custom index and cancellation never need a live Revit process', { skip: !available }, async () => {
  const root = await fs.realpath(await fs.mkdtemp(path.join(os.tmpdir(), 'revit-launcher-test-')));
  try {
    const programFiles = path.join(root, 'Program Files');
    const revit = path.join(programFiles, 'Autodesk/Revit 2026');
    const revit22 = path.join(programFiles, 'Autodesk/Revit 2022');
    const futureRevit = path.join(programFiles, 'Autodesk/Revit 2031');
    const customRevit = path.join(root, 'Custom installation 2025');
    const noExtractor = path.join(programFiles, 'Autodesk/Revit 2030');
    for (const directory of [revit, revit22, futureRevit, customRevit, noExtractor]) {
      await fs.mkdir(path.join(directory, 'RevitExtractor'), { recursive: true });
      if (directory !== noExtractor) await fs.writeFile(path.join(directory, 'RevitExtractor/RevitExtractor.exe'), 'TEST STUB - NOT EXECUTABLE');
      await fs.writeFile(path.join(directory, 'Revit.exe'), 'TEST STUB - NOT EXECUTABLE');
    }
    const model = path.join(root, 'Model with spaces.rvt');
    await fs.writeFile(model, 'TEST MODEL');
    const custom = path.join(root, 'custom.json');
    const customBytes = Buffer.from('\uFEFF{"metadata":{"parameters":{"derivative_type":{"3dviewing":{"view_unique_ids":["only-this-view"]}}}}}\r\n');
    await fs.writeFile(custom, customBytes);
    const bad = path.join(root, 'bad.json'); await fs.writeFile(bad, '{broken');
    const schema = path.join(root, 'schema.json'); await fs.writeFile(schema, '{}');

    async function run(name, args = '', answers = ['', 'T'], installationArgs = `-RevitDirectory ${quote(revit)}`, expectedRevit = revit, entrypoint = launcher) {
      const output = path.join(root, name);
      const wrapper = path.join(root, `${name}.ps1`);
      // Fake installation/version/process: the test must never execute Autodesk binaries.
      // All filesystem writes remain in this temporary fixture.
      await fs.writeFile(wrapper, `
$ErrorActionPreference = 'Stop'
$env:ProgramFiles = ${quote(programFiles)}
$global:answers = [Collections.Generic.Queue[string]]::new()
${answers.map(answer => `$global:answers.Enqueue(${quote(answer)})`).join('\n')}
function Read-Host { param($Prompt); Write-Host "[PROMPT] $Prompt"; if (!$global:answers.Count) { throw "Unexpected prompt: $Prompt" }; return $global:answers.Dequeue() }
function Get-Item {
  param($LiteralPath)
  $major = if ($LiteralPath -match '2022') { 22 } elseif ($LiteralPath -match '2025') { 25 } elseif ($LiteralPath -match '2031') { 31 } else { 26 }
  return [pscustomobject]@{VersionInfo=[pscustomobject]@{FileMajorPart=$major;ProductVersion='2025.3.0.12'}}
}
function Test-Path {
  param($LiteralPath, $PathType)
  if ($LiteralPath -like 'HKLM:*') { return $true }
  return Microsoft.PowerShell.Management\\Test-Path @PSBoundParameters
}
function Get-ChildItem {
  param($LiteralPath, [switch]$Directory, $Filter)
  if ($LiteralPath -like 'HKLM:*') {
    if ($LiteralPath -like '*2025') { return [pscustomobject]@{PSPath='HKLM:InstallFixture'} }
    if ($LiteralPath -like '*2022') { return [pscustomobject]@{PSPath='HKLM:DuplicateFixture'} }
    if ($LiteralPath -like '*Revit') {
      return @([pscustomobject]@{PSChildName='2025';PSPath='HKLM:2025'}, [pscustomobject]@{PSChildName='2022';PSPath='HKLM:2022'})
    }
    return
  }
  return Microsoft.PowerShell.Management\\Get-ChildItem @PSBoundParameters
}
function Get-ItemProperty {
  param($LiteralPath)
  if ($LiteralPath -eq 'HKLM:InstallFixture') { return [pscustomobject]@{InstallationLocation=${quote(customRevit)}} }
  if ($LiteralPath -eq 'HKLM:DuplicateFixture') { return [pscustomobject]@{InstallationLocation=${quote(revit22 + path.sep)}} }
  return [pscustomobject]@{}
}
function Start-Process {
  param($FilePath,$ArgumentList,$WorkingDirectory,[switch]$Wait,[switch]$PassThru,$WindowStyle,$RedirectStandardOutput,$RedirectStandardError)
  if ($FilePath -ne ${quote(path.join(expectedRevit, 'RevitExtractor/RevitExtractor.exe'))}) { throw 'Unexpected executable' }
  if ($WorkingDirectory -ne ${quote(expectedRevit)}) { throw 'Wrong Revit working directory' }
  if (!$ArgumentList.Contains(${quote(expectedRevit)})) { throw 'Missing chosen RCEPath' }
  $runIndex = [regex]::Match($ArgumentList, '^"([^"]+)"').Groups[1].Value
  if (!(Test-Path -LiteralPath $runIndex)) { throw 'index.json must exist before process start' }
  $runRoot = Split-Path -Parent $runIndex
  [IO.File]::WriteAllText((Join-Path $runRoot 'arguments.txt'), $ArgumentList)
  [IO.File]::WriteAllText((Join-Path $runRoot 'output/bubble.json'), '{"type":"design"}')
  [void][IO.Directory]::CreateDirectory((Join-Path $runRoot 'output/Resource'))
  [IO.File]::WriteAllText($RedirectStandardOutput, 'Success Jobs: 1, Failed Jobs: 0')
  [IO.File]::WriteAllText($RedirectStandardError, '')
  return [pscustomobject]@{ExitCode=0}
}
& ${quote(entrypoint)} -ModelPath ${quote(model)} ${installationArgs} -OutputParent ${quote(output)} -NoPause ${args}
exit $LASTEXITCODE
`, 'utf8');
      const result = spawnSync(shell, ['-NoProfile', '-File', wrapper], { encoding: 'utf8', timeout: 30000 });
      if (result.error) throw result.error;
      return { ...result, output };
    }
    const defaultRun = await run('default-enter');
    assert.equal(defaultRun.status, 0, defaultRun.stdout + defaultRun.stderr);
    const [runName] = await fs.readdir(defaultRun.output);
    const runRoot = path.join(defaultRun.output, runName);
    const bytes = await fs.readFile(path.join(runRoot, 'index.json'));
    assert.notDeepEqual([...bytes.subarray(0, 3)], [0xef, 0xbb, 0xbf], 'Default JSON must be UTF-8 without BOM');
    assert.deepEqual(JSON.parse(bytes), { metadata: { parameters: { derivative_type: { '2dviewing': {}, '3dviewing': {}, properties_data: { pdb: true } } } } });
    const argsText = await fs.readFile(path.join(runRoot, 'arguments.txt'), 'utf8');
    const args = [...argsText.matchAll(/"([^"]*)"/g)].map(match => match[1]);
    // Windows may expand an 8.3 temporary path when resolving OutputParent.
    assert.equal(await fs.realpath(args[0]), await fs.realpath(path.join(runRoot, 'index.json')));
    assert.equal(await fs.realpath(args[1]), await fs.realpath(model));
    assert.equal(args[2], '-RCEPath'); assert.equal(args[4], '-LogPath'); assert.equal(args[6], '-journalPath');

    const customRun = await run('custom', `-IndexPath ${quote(custom)}`, ['T']);
    assert.equal(customRun.status, 0, customRun.stdout + customRun.stderr);
    const [customName] = await fs.readdir(customRun.output);
    assert.deepEqual(await fs.readFile(path.join(customRun.output, customName, 'index.json')), customBytes);
    assert.deepEqual(await fs.readFile(custom), customBytes, 'Source index must not change');

    for (const [name, args, answers, expected] of [
      ['validate-default', '-ValidateOnly', [], 0],
      ['validate-explicit', '-UseDefaultIndex -ValidateOnly', [], 0],
      ['validate-custom', `-IndexPath ${quote(custom)} -ValidateOnly`, [], 0],
      ['cancel-confirmation', '', ['', 'N'], 0],
      ['cancel-index', '', ['Q'], 1],
      ['invalid-json', `-IndexPath ${quote(bad)} -ValidateOnly`, [], 1],
      ['invalid-schema', `-IndexPath ${quote(schema)} -ValidateOnly`, [], 1],
      ['missing-index', `-IndexPath ${quote(path.join(root, 'missing.json'))} -ValidateOnly`, [], 1],
      ['conflict', `-IndexPath ${quote(custom)} -UseDefaultIndex`, [], 1]
    ]) {
      const result = await run(name, args, answers);
      assert.equal(result.status, expected, `${name}: ${result.stdout}${result.stderr}`);
      await assert.rejects(fs.access(result.output), `${name} must not create output or invoke the exporter`);
    }
    // A version choice is the first prompt, including when several releases are installed.
    const selected = await run('choose-2022', '', ['2022', '', 'T'], '', revit22);
    assert.equal(selected.status, 0, selected.stdout + selected.stderr);
    assert.match(selected.stdout, /Wybrano Revit 2022/);
    assert.match(selected.stdout, /Extractor:\s+2025\.3\.0\.12/);
    assert.match(selected.stdout.match(/\[PROMPT\].*/)[0], /Numer pozycji/);
    assert.doesNotMatch(selected.stdout, /Revit 2030 -/);

    for (const [name, installationArgs, answers, expectedRevit] of [
      ['choose-menu-number', '', ['4', '', 'T'], revit22],
      ['retry-invalid-choice', '', ['', 'bad', '99999999999', '2022', '', 'T'], revit22],
      ['choose-future-version', '', ['2031', '', 'T'], futureRevit],
      ['choose-registry-location', '', ['2025', '', 'T'], customRevit],
      ['choose-manual-folder', '', ['M', noExtractor, 'M', customRevit, '', 'T'], customRevit],
      ['explicit-version', '-RevitVersion 2022', ['', 'T'], revit22],
      ['matching-version-and-directory', `-RevitVersion 2022 -RevitDirectory ${quote(revit22)}`, ['', 'T'], revit22],
      ['legacy-entrypoint', '-RevitVersion 2022', ['', 'T'], revit22]
    ]) {
      const entrypoint = name === 'legacy-entrypoint'
        ? fileURLToPath(new URL('../../extractorScript_v1.ps1', import.meta.url)) : launcher;
      const result = await run(name, '', answers, installationArgs, expectedRevit, entrypoint);
      assert.equal(result.status, 0, `${name}: ${result.stdout}${result.stderr}`);
    }
    for (const [name, args, installationArgs, answers, expected] of [
      ['validate-version-2022', '-ValidateOnly', '-RevitVersion 2022', [], 0],
      ['validate-registry-2025', '-ValidateOnly', '-RevitVersion 2025', [], 0],
      ['validate-no-version', '-ValidateOnly', '', [], 1],
      ['validate-missing-version', '-ValidateOnly', '-RevitVersion 2029', [], 1],
      ['validate-without-extractor', '-ValidateOnly', `-RevitDirectory ${quote(noExtractor)}`, [], 1],
      ['version-directory-mismatch', '-ValidateOnly', `-RevitVersion 2022 -RevitDirectory ${quote(revit)}`, [], 1],
      ['cancel-version', '', '', ['Q'], 1],
      ['cancel-manual-folder', '', '', ['M', 'Q'], 1]
    ]) {
      const result = await run(name, args, answers, installationArgs);
      assert.equal(result.status, expected, `${name}: ${result.stdout}${result.stderr}`);
      assert.doesNotMatch(result.stdout, /Unexpected prompt/);
      await assert.rejects(fs.access(result.output), `${name} must not start export or create output`);
    }
  } finally {
    assert.equal(path.dirname(root), await fs.realpath(os.tmpdir()));
    assert.ok(path.basename(root).startsWith('revit-launcher-test-'));
    await fs.rm(root, { recursive: true, force: true });
  }
});
