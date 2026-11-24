import {element, pretty} from './client.js';

const labels = {READY:'通过', MISMATCH:'差异待复核', PENDING:'待复核', APPROVED:'已签发', HELD:'已暂缓', ISSUED:'已签发', BLOCKED:'核对未完整'};
const headers = ['业务分组', '输入行', '计算值', '参考值', '判定'];

export function badge(status) {
  return element('span', labels[status] || status, {class:'badge', 'data-result':status, title: status});
}

function issuanceCell(group, committed) {
  if (group.state === 'ISSUED') return badge('ISSUED');
  if (!group.issuable) return badge('BLOCKED');
  if (committed) return element('button', '签发', {type:'button', 'data-issue':group.case});
  return element('span', '可签发', {class:'badge', 'data-result':'READY'});
}

function groupDetail(group, orphans) {
  const detail = {
    判定: group.status,
    核对: {输入: group.ledger.input, 采信: group.ledger.accepted, 隔离: group.ledger.isolated, 被拒: group.ledger.rejected},
    记录键: {
      采信: group.records.accepted,
      隔离: group.records.isolated.map(row => row.record),
      被拒: group.records.rejected.map(row => row.record),
    },
  };
  if (group.holds.length) detail.阻碍 = group.holds;
  else if (!group.issuable && orphans.length) detail.阻碍 = '隔离行无法归属设备组，本组不能视为已完整核对';
  detail.签发 = group.state === 'ISSUED' ? `已签发 · ${group.issued}` : (group.issuable ? '待签发' : '不可签发');
  if (group.evidence) detail.证据 = group.evidence;
  return detail;
}

export function snapshot(report, selected, stage, issuance = {groups:[], orphans:[], committed:false}) {
  const stats = report.intake;
  document.querySelector('[data-metric="input"]').textContent = stats.input;
  document.querySelector('[data-metric="accepted"]').textContent = stats.accepted;
  document.querySelector('[data-metric="isolated"]').textContent = stats.rejected;
  document.querySelector('[data-metric="cases"]').textContent = report.cases?.length ?? '—';
  const table = document.querySelector('#rows');
  table.replaceChildren();
  const head = element('tr');
  const body = table.createTBody();
  if (stage === 'intake') {
    head.append(...['源行', '记录键', '业务分组', '原因码'].map(title => element('th', title, {scope:'col'})));
    for (const item of stats.isolation) {
      const tr = body.insertRow();
      tr.append(...[item.line,item.record,item.case,item.reason].map(value=>element('td',value)));
    }
    if (!stats.isolation.length) body.insertRow().insertCell().textContent = '当前文件没有隔离行';
  } else {
    const withIssuance = issuance.groups.length > 0;
    head.append(...(withIssuance ? [...headers, '签发'] : headers).map(title => element('th', title, {scope:'col'})));
    for (const row of report.cases || []) {
      const tr = body.insertRow();
      const button = element('button',row.case,{type:'button','data-case':row.case,'aria-pressed':String(row.case===selected)});
      tr.insertCell().append(button);
      [row.records.length, row.measure?.value ?? '—', row.measure?.expected ?? '—'].forEach(value=>tr.insertCell().textContent=value);
      tr.insertCell().append(badge(row.status));
      if (withIssuance) {
        const group = issuance.groups.find(item => item.case === row.case);
        if (group) tr.insertCell().append(issuanceCell(group, issuance.committed));
      }
    }
  }
  table.createTHead().append(head);
  const picked = report.cases?.find(row=>row.case===selected);
  const pickedGroup = issuance.groups.find(item => item.case === selected);
  document.querySelector('#detail-title').textContent = picked ? `分组 ${picked.case}` : '采信摘要';
  const shown = pickedGroup ? groupDetail(pickedGroup, issuance.orphans)
    : picked ? picked.measure?.evidence ?? picked.prep?.details ?? {原因:picked.status} : stats.reasons;
  document.querySelector('#detail').textContent = pretty(shown);
  const issued = issuance.groups.filter(item => item.state === 'ISSUED').length;
  const orphanNote = issuance.orphans.length ? ` · ${issuance.orphans.length} 行无法归属` : '';
  document.querySelector('#counts').textContent = report.balance
    ? `行数 ${report.balance.accounted}/${report.balance.input} · ${report.balance.ready} 组通过 · ${issued} 组已签发${orphanNote}`
    : `采信 ${stats.accepted} 行 · 隔离 ${stats.rejected} 行${orphanNote}`;
}

export function history(items, active) {
  const target = document.querySelector('#history');
  target.replaceChildren();
  for (const run of items) {
    const button = element('button', run.id.slice(0,10), {'data-run':run.id,'aria-pressed':String(run.id===active),type:'button'});
    const item = element('li');
    item.append(button, badge(run.status));
    target.append(item);
  }
  if (!items.length) target.append(element('li','尚无执行批次'));
}
