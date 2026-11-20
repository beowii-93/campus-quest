const state = {
  user: null,
  challenges: [],
  myQuests: [],
  filter: 'All',
  activityType: 'All',
  search: '',
  authMode: 'login',
  selectedChallenge: null,
  weeklyChallenge: null,
  selectedTeam: null,
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];


function applyTheme(theme, persist = false) {
  const selected = theme === 'dark' ? 'dark' : 'light';
  document.documentElement.dataset.theme = selected;
  const toggle = $('#themeToggle');
  if (toggle) {
    const next = selected === 'dark' ? 'light' : 'dark';
    const label = next === 'dark' ? 'Dark mode' : 'Light mode';
    toggle.setAttribute('aria-label', `Switch to ${next} mode`);
    toggle.setAttribute('title', `Switch to ${next} mode`);
    toggle.setAttribute('aria-pressed', String(selected === 'dark'));
    toggle.querySelector('.theme-icon').textContent = selected === 'dark' ? '☀' : '☾';
    toggle.querySelector('.theme-label').textContent = label;
  }
  const themeMeta = $('#themeColorMeta');
  if (themeMeta) themeMeta.content = selected === 'dark' ? '#151918' : '#faf9f6';
  if (persist) {
    try { localStorage.setItem('campusquest-theme', selected); } catch (_) { /* private browsing may block storage */ }
  }
}

const initialTheme = document.documentElement.dataset.theme || 'light';
applyTheme(initialTheme, false);
$('#themeToggle')?.addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.themeSource = 'manual';
  applyTheme(next, true);
});

// Follow OS theme changes only until the student makes an explicit choice.
try {
  const themePreference = window.matchMedia('(prefers-color-scheme: dark)');
  const syncSystemTheme = (event) => {
    if (!localStorage.getItem('campusquest-theme')) applyTheme(event.matches ? 'dark' : 'light');
  };
  if (themePreference.addEventListener) themePreference.addEventListener('change', syncSystemTheme);
  else if (themePreference.addListener) themePreference.addListener(syncSystemTheme);
} catch (_) { /* Theme still works with the manual toggle if media queries are unavailable. */ }

async function api(path, options = {}) {
  const config = { method: options.method || 'GET', headers: { ...(options.headers || {}) }, credentials: 'same-origin' };
  if (options.body !== undefined) {
    config.headers['Content-Type'] = 'application/json';
    config.body = JSON.stringify(options.body);
  }
  if (!['GET', 'HEAD', 'OPTIONS'].includes(config.method.toUpperCase())) {
    const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
    if (csrf) config.headers['X-CSRF-Token'] = csrf;
  }
  const response = await fetch(path, config);
  const data = await response.json().catch(() => ({ ok: false, error: 'The server returned an unreadable response.' }));
  if (!response.ok || data.ok === false) throw new Error(data.error || 'Something went wrong. Please try again.');
  return data;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  })[char]);
}

function toast(message) {
  const node = $('#toast');
  node.textContent = message;
  node.classList.add('show');
  window.clearTimeout(toast.timer);
  toast.timer = window.setTimeout(() => node.classList.remove('show'), 2900);
}

function openModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.remove('hidden');
}
function closeModal(id) {
  const modal = document.getElementById(id);
  if (modal) modal.classList.add('hidden');
}
function requireLogin() {
  if (state.user) return true;
  openAuth('login');
  toast('Sign in to make this little quest yours.');
  return false;
}

function openAuth(mode = 'login') {
  setAuthMode(mode);
  $('#authMessage').textContent = '';
  openModal('authModal');
}
function setAuthMode(mode) {
  state.authMode = mode;
  $$('.auth-tab').forEach(tab => tab.classList.toggle('active', tab.dataset.authMode === mode));
  $('#nameField').classList.toggle('hidden', mode !== 'register');
  $('#authTitle').innerHTML = mode === 'register' ? 'Make room for<br><em>new little wins.</em>' : 'Your campus story<br><em>starts here.</em>';
  $('#authSubmit').innerHTML = mode === 'register' ? 'Create my account <span class="button-arrow">↗</span>' : 'Sign in <span class="button-arrow">↗</span>';
  $('#authPassword').autocomplete = mode === 'register' ? 'new-password' : 'current-password';
  $('#authPassword').minLength = mode === 'register' ? 8 : 1;
}

function updateHeader() {
  const authButton = $('#authButton');
  const avatarButton = $('#profileButton');
  if (state.user) {
    authButton.textContent = 'Sign out';
    avatarButton.classList.remove('hidden');
    avatarButton.textContent = (state.user.name || 'Y').trim().charAt(0).toUpperCase();
    $('#signedInLabel').textContent = `hey, ${state.user.name.split(' ')[0]}`;
  } else {
    authButton.innerHTML = 'Sign in <span class="button-arrow">↗</span>';
    avatarButton.classList.add('hidden');
    $('#signedInLabel').textContent = 'your campus, your quest';
  }
}

const artByCategory = {
  Tech: '⌘', Creative: '✿', Social: '♡', Wellbeing: '☁', Sports: '🏸',
  Career: '✧', Community: '☀', Sustainability: '♻', Culture: '🌍', Games: '🧩', Learning: '📚'
};
const accentMap = { blue: 'accent-blue', mint: 'accent-mint', peach: 'accent-peach', lilac: 'accent-lilac', pink: 'accent-pink' };

function renderChallenges() {
  const visible = state.challenges.filter(challenge => {
    const categoryMatch = state.filter === 'All' || challenge.category === state.filter;
    const typeMatch = state.activityType === 'All' || challenge.activity_type === state.activityType;
    const haystack = `${challenge.title} ${challenge.description} ${challenge.category} ${challenge.activity_type || ''} ${challenge.badge_name}`.toLowerCase();
    return categoryMatch && typeMatch && (!state.search || haystack.includes(state.search.toLowerCase()));
  });
  $('#questCount').textContent = String(visible.length).padStart(2, '0');
  const grid = $('#challengeGrid');
  if (!visible.length) {
    grid.innerHTML = '<div class="empty-filter">No quests found for that little search. Try another word or category.</div>';
    return;
  }
  grid.innerHTML = visible.map(challenge => {
    const joined = challenge.joined;
    const completed = challenge.status === 'completed';
    const submitted = challenge.status === 'submitted';
    const ready = challenge.status === 'ready_to_submit';
    const rejected = challenge.status === 'submission_rejected';
    let action = `<button class="challenge-action" data-action="join" data-id="${challenge.id}">Join quest ↗</button>`;
    if (completed) action = '<button class="challenge-action completed" disabled>Approved ✓</button>';
    else if (submitted) action = '<button class="challenge-action pending" disabled>In review ◷</button>';
    else if (rejected) action = '<button class="challenge-action pending" disabled>Contact moderator</button>';
    else if (ready) action = `<button class="challenge-action joined" data-action="submit" data-id="${challenge.id}">Submit final work ↗</button>`;
    else if (joined) action = `<button class="challenge-action joined" data-action="checkin" data-id="${challenge.id}" data-title="${escapeHtml(challenge.title)}">Check in +</button>`;
    return `
      <article class="challenge-card ${accentMap[challenge.accent] || 'accent-blue'}">
        <div class="challenge-top"><span class="category-label">${escapeHtml(challenge.category)}</span><span class="duration-pill">${challenge.duration_days} days · ${escapeHtml(challenge.difficulty)}</span></div>
        <span class="activity-type-pill">${escapeHtml(challenge.activity_type || 'Challenge')}</span>
        <button class="challenge-art" type="button" data-open-challenge="${challenge.id}" aria-label="View ${escapeHtml(challenge.title)} details">${artByCategory[challenge.category] || '✦'}</button>
        <h3>${escapeHtml(challenge.title)}</h3>
        <p>${escapeHtml(challenge.description)}</p>
        <div class="challenge-meta"><span>✧ ${escapeHtml(challenge.badge_name)} badge</span><span class="meta-sep">·</span><span>${challenge.team_allowed ? 'Squad friendly' : 'Solo quest'}</span></div>
        <div class="challenge-bottom"><span class="challenge-badge">${escapeHtml(challenge.badge_emoji)} ${escapeHtml(challenge.badge_name)}</span>${action}</div>
        <div class="challenge-card-foot"><span>${Number(challenge.participant_count || 0)} joined</span><button class="challenge-details-link" type="button" data-open-challenge="${challenge.id}">View mission ↗</button></div>
      </article>`;
  }).join('');
}

function openChallengeDetails(id) {
  const challenge = state.challenges.find(item => item.id === Number(id)) || (state.weeklyChallenge?.id === Number(id) ? state.weeklyChallenge : null);
  if (!challenge) return;
  state.selectedChallenge = challenge;
  $('#challengeDetailCategory').textContent = `${challenge.category} · ${challenge.activity_type || 'Challenge'} · ${challenge.difficulty}`;
  $('#challengeDetailTitle').textContent = challenge.title;
  $('#challengeDetailDescription').textContent = challenge.description;
  $('#challengeDetailBadge').textContent = `${challenge.badge_emoji} ${challenge.badge_name}`;
  $('#challengeDetailFacts').innerHTML = [
    `${challenge.duration_days} days`,
    challenge.activity_type || 'Challenge',
    challenge.team_allowed ? 'Squad friendly' : 'Solo quest',
    `${Number(challenge.participant_count || 0)} participants`
  ].map(text => `<span class="detail-fact">${escapeHtml(text)}</span>`).join('');
  $('#challengeDetailMission').textContent = challenge.details || challenge.description;
  const status = challenge.status;
  const note = $('#challengeDetailStatusNote');
  const button = $('#challengeDetailPrimary');
  button.disabled = false;
  button.dataset.challengeId = challenge.id;
  if (status === 'completed') {
    button.textContent = 'Quest approved ✓'; button.disabled = true;
    note.textContent = 'You completed this quest and your badge was awarded after review.';
  } else if (status === 'submitted') {
    button.textContent = 'Awaiting review ◷'; button.disabled = true;
    note.textContent = 'Your final work is with the moderation team. Your badge will appear after approval.';
  } else if (status === 'submission_rejected') {
    button.textContent = 'Submission rejected'; button.disabled = true;
    note.textContent = 'This submission was rejected. Contact a moderator if you believe this was a mistake.';
  } else if (status === 'ready_to_submit') {
    button.textContent = 'Submit final work ↗';
    note.textContent = 'You finished the daily steps. Share your final work to request completion review.';
  } else if (challenge.joined) {
    button.textContent = 'Check in today +';
    note.textContent = `Your progress: ${challenge.progress || 0} of ${challenge.duration_days} check-ins.`;
  } else {
    button.textContent = 'Join this quest ↗';
    note.textContent = 'Join to add this quest to My Quests and start checking in.';
  }
  $('#challengeReportForm').classList.add('hidden');
  $('#reportMessage').textContent = '';
  $('#reportDetails').value = '';
  openModal('challengeDetailModal');
}

function openFinalSubmission(id) {
  if (!requireLogin()) return;
  const quest = state.challenges.find(item => item.id === Number(id)) || state.myQuests.find(item => item.id === Number(id));
  if (!quest) return;
  $('#finalSubmitChallengeId').value = id;
  $('#finalSubmitQuestName').textContent = `Final work for “${quest.title}”. Share a link or a short reflection. A moderator reviews it before your completion badge is awarded.`;
  $('#finalSubmitNote').value = '';
  $('#finalSubmitProof').value = '';
  $('#finalSubmitMessage').textContent = '';
  openModal('finalSubmitModal');
}


function renderMyQuests() {
  const node = $('#myQuestsList');
  if (!state.user) {
    node.innerHTML = '<div class="empty-state">Sign in to save your quests, check in and collect your little keepsakes.<br><button class="inline-link" id="emptySignIn">Sign in →</button></div>';
    $('#emptySignIn')?.addEventListener('click', () => openAuth('login'));
    return;
  }
  if (!state.myQuests.length) {
    node.innerHTML = '<div class="empty-state">Your quest list is still a blank page.<br><a class="inline-link" href="#explore">Find a little adventure →</a></div>';
    return;
  }
  node.innerHTML = state.myQuests.slice(0, 5).map(quest => {
    const percent = Math.min(100, Math.round((quest.progress / quest.duration_days) * 100));
    const done = quest.status === 'completed';
    const pending = quest.status === 'submitted';
    const ready = quest.status === 'ready_to_submit';
    const rejected = quest.status === 'submission_rejected';
    const closed = quest.status === 'challenge_closed';
    const statusText = done ? 'Approved · badge earned' : pending ? 'Final work waiting for review' : rejected
      ? `Submission rejected${quest.final_review_feedback ? `: ${quest.final_review_feedback}` : ' · contact a moderator'}`
      : closed ? 'This quest was closed by the moderation team.'
      : ready ? (quest.final_review_feedback ? `Changes requested: ${quest.final_review_feedback}` : 'Daily steps complete · final work needed')
      : `${quest.progress} of ${quest.duration_days} check-ins`;
    const action = ready ? `<button class="mini-action" data-action="submit" data-id="${quest.id}">Submit work ↗</button>` : pending ? '<span class="mini-status">In review ◷</span>' : done ? '<span class="mini-status">Completed ✓</span>' : (rejected || closed) ? '<span class="mini-status">Closed</span>' : `<button class="mini-action" data-action="checkin" data-id="${quest.id}" data-title="${escapeHtml(quest.title)}">Check in +</button>`;
    return `<div class="my-quest-row">
      <div class="quest-icon">${artByCategory[quest.category] || '✦'}</div>
      <div class="my-quest-info"><h4>${escapeHtml(quest.title)}</h4><p>${statusText}</p></div>
      <div class="quest-progress"><div class="progress-track"><span style="width:${percent}%"></span></div><span class="progress-label">${action}</span></div>
    </div>`;
  }).join('');
}


function renderBadges(badges) {
  const earned = badges.filter(badge => badge.earned);
  $('#badgeCount').textContent = `${earned.length} earned`;
  const shelf = $('#badgeShelf');
  shelf.innerHTML = badges.map(badge => `<div class="${badge.earned ? 'badge-item' : 'badge-locked'}" title="${escapeHtml(badge.description)}">${escapeHtml(badge.emoji)}<small>${escapeHtml(badge.name)}</small></div>`).join('');
}

function renderHeatmap(days, activeDays) {
  $('#activityTotal').textContent = `${activeDays} active days`;
  const monthNode = $('#heatmapMonths');
  if (monthNode && days.length) {
    const labels = [];
    let previousMonth = -1;
    days.forEach(day => {
      const parsed = new Date(`${day.date}T12:00:00Z`);
      const month = parsed.getUTCMonth();
      if (month !== previousMonth) {
        labels.push(parsed.toLocaleString(undefined, { month: 'short', timeZone: 'UTC' }));
        previousMonth = month;
      }
    });
    monthNode.innerHTML = labels.map(label => `<span>${escapeHtml(label)}</span>`).join('');
  }
  const grid = $('#heatmapGrid');
  grid.innerHTML = days.map(day => {
    const count = day.count;
    const level = count === 0 ? 0 : count === 1 ? 1 : count === 2 ? 2 : 3;
    return `<span class="heat-cell level-${level}" title="${day.date}: ${count} ${count === 1 ? 'activity' : 'activities'}"></span>`;
  }).join('');
}

function renderTeams(teams) {
  const node = $('#teamList');
  if (!teams.length) {
    node.innerHTML = '<div class="empty-state">No squads yet. Start one for a quest you love, then invite your people.</div>';
    return;
  }
  node.innerHTML = teams.map((team, index) => {
    const places = Math.max(0, Number(team.capacity) - Number(team.member_count));
    const stateLabel = team.joined ? 'Member ✓' : team.requested ? 'Request pending ◷' : Number(team.member_count) >= Number(team.capacity) ? 'Squad full' : team.can_join ? 'Open squad ↗' : 'Join quest first';
    return `<article class="team-card">
      <div class="team-art">${['✿', '⌘', '☀', '✧'][index % 4]}</div>
      <div class="team-info"><h4>${escapeHtml(team.name)}</h4><p>${escapeHtml(team.description || 'A squad making a little progress together.')}</p><small>${escapeHtml(team.challenge_title)} · ${team.member_count}/${team.capacity} people · ${places} ${places === 1 ? 'spot' : 'spots'} open · started by ${escapeHtml(team.creator_name)}</small></div>
      <button class="team-join" data-team-detail="${team.id}">${stateLabel}</button>
    </article>`;
  }).join('');
}

async function openTeamDetails(teamId) {
  if (!requireLogin()) return;
  try {
    const result = await api(`/api/teams/${teamId}`);
    const team = result.team;
    state.selectedTeam = team;
    $('#teamDetailTitle').textContent = team.name;
    $('#teamDetailDescription').textContent = team.description || `A squad taking on ${team.challenge_title}.`;
    $('#teamDetailFacts').innerHTML = [team.challenge_title, `${team.member_count}/${team.capacity} members`, `${Math.max(0, team.capacity - team.member_count)} spots open`]
      .map(value => `<span class="detail-fact">${escapeHtml(value)}</span>`).join('');
    $('#teamMemberList').innerHTML = `<span class="panel-label">SQUAD MEMBERS</span>` + result.members.map(member => `
      <div class="team-member-row"><span class="team-member-avatar">${escapeHtml(member.name.charAt(0).toUpperCase())}</span><span><strong>${escapeHtml(member.name)}</strong><small>${escapeHtml(member.department || 'CampusQuest member')} · ${escapeHtml(member.study_year || 'Student')}</small></span><em>${escapeHtml(member.role)}</em></div>`).join('');

    const requestButton = $('#teamRequestButton');
    requestButton.classList.toggle('hidden', Boolean(team.is_member) || Boolean(team.is_owner));
    requestButton.disabled = false;
    requestButton.dataset.teamId = team.id;
    if (team.requested) { requestButton.textContent = 'Request sent · waiting'; requestButton.disabled = true; }
    else if (!team.can_join) { requestButton.textContent = 'Join the quest first / one squad per quest'; requestButton.disabled = true; }
    else if (team.is_full) { requestButton.textContent = 'Squad is full'; requestButton.disabled = true; }
    else requestButton.textContent = 'Request to join squad ↗';
    $('#teamViewQuestButton').classList.toggle('hidden', Boolean(team.can_join) || Boolean(team.is_member));
    $('#teamViewQuestButton').dataset.challengeId = team.challenge_id;

    const requestWrap = $('#teamRequestList');
    if (team.is_owner && result.requests.length) {
      requestWrap.classList.remove('hidden');
      $('#teamRequests').innerHTML = result.requests.map(request => `<div class="team-request-row"><span><strong>${escapeHtml(request.name)}</strong><small>${escapeHtml(request.department || 'Student')} · ${escapeHtml(request.study_year || '')}</small></span><span><button class="mini-action" data-team-request-review="accept" data-id="${request.id}">Accept</button><button class="mini-action danger" data-team-request-review="decline" data-id="${request.id}">Decline</button></span></div>`).join('');
    } else { requestWrap.classList.add('hidden'); $('#teamRequests').innerHTML = ''; }

    const kudosForm = $('#peerKudosForm');
    if (team.is_member && result.members.length > 1) {
      kudosForm.classList.remove('hidden');
      $('#kudosRecipient').innerHTML = result.members.filter(member => member.id !== state.user.id)
        .map(member => `<option value="${member.id}">${escapeHtml(member.name)}</option>`).join('');
      $('#kudosMessage').value = '';
      $('#kudosMessageStatus').textContent = '';
    } else kudosForm.classList.add('hidden');
    openModal('teamDetailModal');
  } catch (error) { toast(error.message); }
}


function renderLeaderboard(leaders) {
  const node = $('#leaderboardList');
  if (!leaders.length) {
    node.innerHTML = '<div class="empty-state">Be the first to show up.</div>';
    return;
  }
  node.innerHTML = leaders.map((person, index) => `<div class="leader-row">
    <span class="leader-number">${String(index + 1).padStart(2, '0')}</span>
    <span class="leader-avatar">${escapeHtml(person.name.charAt(0).toUpperCase())}</span>
    <span class="leader-person"><strong>${escapeHtml(person.name)}</strong><small>${person.completed} finished · ${person.joined} joined</small></span>
    <span class="leader-badges">✦ ${person.badges}</span>
  </div>`).join('');
}

function renderPendingChallenges(challenges) {
  const node = $('#pendingChallenges');
  if (!node) return;
  if (!challenges.length) {
    node.innerHTML = '<div class="empty-state">No quests are waiting for review. Lovely and quiet.</div>';
    return;
  }
  node.innerHTML = challenges.map(challenge => `
    <article class="admin-queue-card">
      <div class="admin-queue-copy">
        <span class="panel-label">${escapeHtml(challenge.category)} · ${challenge.duration_days} DAYS</span>
        <h3>${escapeHtml(challenge.title)}</h3>
        <p>${escapeHtml(challenge.description)}</p>
        <small>Suggested by ${escapeHtml(challenge.creator_name || 'a student')}</small>
      </div>
      <div class="admin-queue-actions">
        <button class="button button-dark button-small" data-admin-review="approve" data-id="${challenge.id}">Approve</button>
        <button class="button button-outline button-small" data-admin-review="reject" data-id="${challenge.id}">Decline</button>
      </div>
    </article>`).join('');
}

function renderPendingSubmissions(items) {
  const node = $('#pendingSubmissions');
  if (!node) return;
  if (!items.length) { node.innerHTML = '<div class="empty-state">No final work is waiting for review.</div>'; return; }
  node.innerHTML = items.map(item => `<article class="admin-queue-card">
    <div class="admin-queue-copy"><span class="panel-label">FINAL WORK · ${escapeHtml(item.challenge_title)}</span><h3>${escapeHtml(item.student_name)}</h3><p>${escapeHtml(item.note || 'No reflection supplied.')}</p>${item.proof_url ? `<a href="${escapeHtml(item.proof_url)}" target="_blank" rel="noopener noreferrer">Open proof link ↗</a>` : ''}<small>Submitted ${escapeHtml(item.created_at)}</small></div>
    <div class="admin-queue-actions"><label class="admin-feedback-label" for="reviewFeedback${item.id}">Feedback (required for changes/rejection)</label><textarea class="admin-review-feedback" id="reviewFeedback${item.id}" maxlength="500" rows="2" placeholder="Give clear, kind and specific feedback…"></textarea><button class="button button-dark button-small" data-submission-review="approve" data-id="${item.id}">Approve</button><button class="button button-outline button-small" data-submission-review="needs_changes" data-id="${item.id}">Request changes</button><button class="mini-action danger" data-submission-review="reject" data-id="${item.id}">Reject submission</button></div>
  </article>`).join('');
}

function renderPendingReports(items) {
  const node = $('#pendingReports');
  if (!node) return;
  if (!items.length) { node.innerHTML = '<div class="empty-state">No reports are waiting for review.</div>'; return; }
  node.innerHTML = items.map(item => `<article class="admin-queue-card">
    <div class="admin-queue-copy"><span class="panel-label">${escapeHtml(item.reason)} · ${escapeHtml(item.challenge_title)}</span><h3>Report from ${escapeHtml(item.reporter_name)}</h3><p>${escapeHtml(item.details || 'No extra context supplied.')}</p><small>Reported ${escapeHtml(item.created_at)}</small></div>
    <div class="admin-queue-actions"><button class="button button-dark button-small" data-report-review="hide_challenge" data-id="${item.id}">Hide quest</button><button class="button button-outline button-small" data-report-review="dismiss" data-id="${item.id}">Dismiss</button></div>
  </article>`).join('');
}

async function refreshWeeklyQuest() {
  const card = $('#weeklyQuestCard');
  if (!card) return;
  try {
    const result = await api('/api/weekly-quest');
    state.weeklyChallenge = result.challenge;
    const challenge = result.challenge;
    card.querySelector('.weekly-card-art').textContent = artByCategory[challenge.category] || '✦';
    card.querySelector('.weekly-card-kicker').textContent = `WEEK ${result.week} · WEEKLY SPOTLIGHT`;
    card.querySelector('h3').textContent = challenge.title;
    card.querySelector('p').textContent = challenge.description;
    $('#weeklyQuestButton').disabled = false;
  } catch (error) {
    card.querySelector('h3').textContent = 'The next quest is getting ready.';
    card.querySelector('p').textContent = 'Explore the board for something that fits your week.';
  }
}

async function refreshAdminTools() {
  const panel = $('#adminTools');
  if (!panel) return;
  if (state.user?.role !== 'admin') {
    panel.classList.add('hidden');
    return;
  }
  panel.classList.remove('hidden');
  try {
    const [challenges, submissions, reports] = await Promise.all([
      api('/api/admin/pending-challenges'), api('/api/admin/pending-submissions'), api('/api/admin/reports')
    ]);
    renderPendingChallenges(challenges.challenges);
    renderPendingSubmissions(submissions.submissions);
    renderPendingReports(reports.reports);
  } catch (error) {
    $('#pendingChallenges').innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
}

async function refreshChallenges() {
  const data = await api('/api/challenges');
  state.challenges = data.challenges;
  renderChallenges();
}
async function refreshPersonal() {
  const me = await api('/api/me');
  state.user = me.user;
  updateHeader();
  const leaderboardOptIn = $('#leaderboardOptIn');
  if (leaderboardOptIn) {
    leaderboardOptIn.disabled = !state.user;
    leaderboardOptIn.checked = Boolean(state.user?.leaderboard_public);
  }
  if (!state.user) {
    state.myQuests = [];
    renderMyQuests();
    $('#badgeShelf').innerHTML = '<div class="badge-locked">✦<small>First Quest</small></div><div class="badge-locked">🏁<small>Finisher</small></div><div class="badge-locked">☀<small>Steady Spark</small></div><div class="badge-locked">✧<small>Squad Star</small></div>';
    $('#badgeCount').textContent = 'sign in to collect';
    $('#heatmapGrid').innerHTML = Array.from({ length: 112 }, () => '<span class="heat-cell level-0"></span>').join('');
    $('#heatmapMonths').innerHTML = '<span>Your activity will bloom here</span>';
    $('#activityTotal').textContent = '— active days';
    return;
  }
  const [quests, badges, activity] = await Promise.all([api('/api/my-quests'), api('/api/badges'), api('/api/activity')]);
  state.myQuests = quests.quests;
  renderMyQuests();
  renderBadges(badges.badges);
  renderHeatmap(activity.days, activity.active_days);
  await refreshChallenges();
}
async function openProfile() {
  if (!requireLogin()) return;
  try {
    const result = await api('/api/me');
    state.user = result.user;
    $('#profileDepartment').value = state.user.department || '';
    $('#profileYear').value = state.user.study_year || '';
    $('#profileBio').value = state.user.bio || '';
    $('#profileInterests').value = state.user.interests || '';
    $('#profilePublic').checked = Boolean(state.user.profile_public);
    $('#profileStats').innerHTML = [
      `${state.user.joined_count || 0} quests joined`,
      `${state.user.completed_count || 0} approved`,
      `${state.user.badge_count || 0} badges`,
      `${state.user.kudos_received || 0} kudos`
    ].map(value => `<span class="profile-stat">${escapeHtml(value)}</span>`).join('');
    const kudos = await api('/api/kudos');
    $('#profileKudos').innerHTML = `<h3>Kind words from teammates</h3>` + (kudos.kudos.length
      ? kudos.kudos.map(item => `<article class="kudos-note"><p>“${escapeHtml(item.message)}”</p><small>${escapeHtml(item.from_name)} · ${escapeHtml(item.challenge_title)}</small></article>`).join('')
      : '<p>Peer kudos will show here when teammates recognize your contribution.</p>');
    $('#profileMessage').textContent = '';
    openModal('profileModal');
  } catch (error) { toast(error.message); }
}

async function refreshCommunity() {
  const [teams, leaders] = await Promise.all([api('/api/teams'), api('/api/leaderboard')]);
  renderTeams(teams.teams);
  renderLeaderboard(leaders.leaders);
}
async function refreshAll() {
  try {
    await refreshChallenges();
    await refreshPersonal();
    await refreshCommunity();
    await refreshAdminTools();
    await refreshWeeklyQuest();
  } catch (error) {
    toast(error.message);
  }
}

function openCheckin(challengeId, title) {
  if (!requireLogin()) return;
  $('#checkinChallengeId').value = challengeId;
  $('#checkinQuestName').textContent = `A note for “${title}” — every check-in moves your quest along.`;
  $('#checkinNote').value = '';
  $('#checkinProof').value = '';
  $('#checkinMessage').textContent = '';
  openModal('checkinModal');
}

async function joinChallenge(id) {
  if (!requireLogin()) return;
  try {
    const result = await api(`/api/challenges/${id}/join`, { method: 'POST', body: {} });
    toast(result.message);
    if (result.new_badges?.length) toast(`Badge earned: ${result.new_badges.join(', ')} ✦`);
    await refreshPersonal();
    await refreshCommunity();
  } catch (error) { toast(error.message); }
}

async function joinTeam(id) {
  if (!requireLogin()) return;
  try {
    const result = await api(`/api/teams/${id}/join`, { method: 'POST', body: {} });
    toast(result.message);
    if (result.new_badges?.length) toast(`Badge earned: ${result.new_badges.join(', ')} ✦`);
    await refreshPersonal();
    await refreshCommunity();
  } catch (error) { toast(error.message); }
}

async function runMuse() {
  const button = $('#museButton');
  button.disabled = true;
  button.textContent = 'Finding a little spark…';
  try {
    const result = await api('/api/muse', {
      method: 'POST',
      body: { mood: $('#moodSelect').value, time: $('#timeSelect').value, interests: [] }
    });
    const quest = result.suggestion;
    const resultNode = $('#museResult');
    resultNode.classList.remove('hidden');
    const joined = quest.joined;
    resultNode.innerHTML = `<div class="result-kicker">A LITTLE NUDGE FOR YOU</div><h4>${escapeHtml(quest.title)}</h4><p>${escapeHtml(result.reason)}</p><button data-muse-action="${quest.id}" data-joined="${joined}">${joined ? 'Open my quest →' : 'Add this quest →'}</button>`;
    resultNode.dataset.title = quest.title;
  } catch (error) { toast(error.message); }
  finally {
    button.disabled = false;
    button.innerHTML = 'Find my little quest <span class="button-arrow">✧</span>';
  }
}

function populateTeamChallengeSelect() {
  const select = $('#teamChallenge');
  const active = state.myQuests.filter(quest => quest.status === 'active');
  select.innerHTML = active.map(quest => `<option value="${quest.id}">${escapeHtml(quest.title)}</option>`).join('');
  return active.length;
}

// Main delegated interactions.
document.addEventListener('click', async (event) => {
  const teamDetailButton = event.target.closest('[data-team-detail]');
  if (teamDetailButton) await openTeamDetails(Number(teamDetailButton.dataset.teamDetail));
  const requestReviewButton = event.target.closest('[data-team-request-review]');
  if (requestReviewButton) {
    requestReviewButton.disabled = true;
    try {
      const result = await api(`/api/team-requests/${requestReviewButton.dataset.id}/review`, { method: 'POST', body: { action: requestReviewButton.dataset.teamRequestReview } });
      toast(result.message); await openTeamDetails(state.selectedTeam.id); await refreshCommunity();
    } catch (error) { toast(error.message); requestReviewButton.disabled = false; }
  }
  const detailButton = event.target.closest('[data-open-challenge]');
  if (detailButton) openChallengeDetails(Number(detailButton.dataset.openChallenge));
  const actionButton = event.target.closest('[data-action]');
  if (actionButton) {
    const id = Number(actionButton.dataset.id);
    if (actionButton.dataset.action === 'join') joinChallenge(id);
    if (actionButton.dataset.action === 'checkin') openCheckin(id, actionButton.dataset.title || state.challenges.find(q => q.id === id)?.title || 'your quest');
    if (actionButton.dataset.action === 'submit') openFinalSubmission(id);
  }
  const reviewButton = event.target.closest('[data-admin-review]');
  if (reviewButton) {
    const action = reviewButton.dataset.adminReview;
    const id = Number(reviewButton.dataset.id);
    reviewButton.disabled = true;
    try {
      const result = await api(`/api/admin/challenges/${id}/review`, { method: 'POST', body: { action } });
      toast(result.message);
      await refreshChallenges();
      await refreshAdminTools();
    } catch (error) {
      toast(error.message);
      reviewButton.disabled = false;
    }
  }
  const teamButton = event.target.closest('[data-team-join]');
  if (teamButton) joinTeam(Number(teamButton.dataset.teamJoin));
  const submissionReview = event.target.closest('[data-submission-review]');
  if (submissionReview) {
    submissionReview.disabled = true;
    try {
      const action = submissionReview.dataset.submissionReview;
      const feedbackField = document.getElementById(`reviewFeedback${submissionReview.dataset.id}`);
      const feedback = feedbackField?.value.trim() || '';
      if (action !== 'approve' && feedback.length < 8) {
        throw new Error('Add at least 8 characters of feedback so the student knows what to do next.');
      }
      const result = await api(`/api/admin/submissions/${submissionReview.dataset.id}/review`, { method: 'POST', body: { action, feedback } });
      toast(result.message); await refreshAdminTools(); await refreshPersonal();
    } catch (error) { toast(error.message); submissionReview.disabled = false; }
  }
  const reportReview = event.target.closest('[data-report-review]');
  if (reportReview) {
    reportReview.disabled = true;
    try {
      const result = await api(`/api/admin/reports/${reportReview.dataset.id}/review`, { method: 'POST', body: { action: reportReview.dataset.reportReview } });
      toast(result.message); await refreshAdminTools(); await refreshChallenges();
    } catch (error) { toast(error.message); reportReview.disabled = false; }
  }
  const detailPrimary = event.target.closest('#challengeDetailPrimary');
  if (detailPrimary && state.selectedChallenge) {
    const quest = state.selectedChallenge;
    closeModal('challengeDetailModal');
    if (!quest.joined) await joinChallenge(quest.id);
    else if (quest.status === 'ready_to_submit') openFinalSubmission(quest.id);
    else if (quest.status !== 'submitted' && quest.status !== 'completed') openCheckin(quest.id, quest.title);
  }
  const reportToggle = event.target.closest('#challengeReportToggle');
  if (reportToggle) {
    if (!requireLogin()) return;
    $('#challengeReportForm').classList.toggle('hidden');
  }
  const teamRequestButton = event.target.closest('#teamRequestButton');
  if (teamRequestButton && state.selectedTeam && !teamRequestButton.disabled) {
    teamRequestButton.disabled = true;
    try {
      const result = await api(`/api/teams/${state.selectedTeam.id}/request`, { method: 'POST', body: {} });
      toast(result.message); await openTeamDetails(state.selectedTeam.id); await refreshCommunity();
    } catch (error) { toast(error.message); teamRequestButton.disabled = false; }
  }
  const viewRelatedQuest = event.target.closest('#teamViewQuestButton');
  if (viewRelatedQuest) { closeModal('teamDetailModal'); openChallengeDetails(Number(viewRelatedQuest.dataset.challengeId)); }
  const museAction = event.target.closest('[data-muse-action]');
  if (museAction) {
    const id = Number(museAction.dataset.museAction);
    const quest = state.challenges.find(item => item.id === id);
    if (quest?.joined) {
      openCheckin(id, quest.title);
    } else joinChallenge(id);
  }
});

$('#authButton').addEventListener('click', async () => {
  if (!state.user) { openAuth('login'); return; }
  try {
    await api('/api/auth/logout', { method: 'POST', body: {} });
    state.user = null;
    state.myQuests = [];
    updateHeader();
    await refreshAll();
    toast('You have signed out. See you soon!');
  } catch (error) { toast(error.message); }
});
$('#profileButton').addEventListener('click', openProfile);
$('#leaderboardOptIn')?.addEventListener('change', async (event) => {
  if (!requireLogin()) { event.target.checked = false; return; }
  const checkbox = event.target;
  checkbox.disabled = true;
  try {
    const result = await api('/api/privacy/leaderboard', { method: 'POST', body: { show: checkbox.checked } });
    state.user.leaderboard_public = result.show;
    toast(result.message);
    await refreshCommunity();
  } catch (error) {
    checkbox.checked = !checkbox.checked;
    toast(error.message);
  } finally { checkbox.disabled = false; }
});
$('#authForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const mode = state.authMode;
  const payload = { email: $('#authEmail').value.trim(), password: $('#authPassword').value };
  if (mode === 'register') payload.name = $('#authName').value.trim();
  const button = $('#authSubmit');
  button.disabled = true;
  $('#authMessage').textContent = 'One moment…';
  try {
    const result = await api(mode === 'register' ? '/api/auth/register' : '/api/auth/login', { method: 'POST', body: payload });
    state.user = result.user;
    closeModal('authModal');
    $('#authForm').reset();
    await refreshAll();
    toast(`Welcome${state.user?.name ? `, ${state.user.name.split(' ')[0]}` : ''}! Let's make something happen.`);
  } catch (error) { $('#authMessage').textContent = error.message; }
  finally { button.disabled = false; }
});
$('#demoLoginButton')?.addEventListener('click', async () => {
  try {
    const result = await api('/api/auth/demo', { method: 'POST', body: {} });
    state.user = result.user;
    closeModal('authModal');
    await refreshAll();
    toast('You are in the demo space. Have a wander!');
  } catch (error) { $('#authMessage').textContent = error.message; }
});
$$('.auth-tab').forEach(tab => tab.addEventListener('click', () => setAuthMode(tab.dataset.authMode)));
$$('[data-close]').forEach(button => button.addEventListener('click', () => closeModal(button.dataset.close)));
$$('.modal-backdrop').forEach(backdrop => backdrop.addEventListener('click', (event) => {
  if (event.target === backdrop) backdrop.classList.add('hidden');
}));
document.addEventListener('keydown', event => {
  if (event.key === 'Escape') $$('.modal-backdrop').forEach(modal => modal.classList.add('hidden'));
});

function applyChallengeFilter(filter, shouldScroll = false) {
  state.filter = filter;
  state.activityType = 'All';
  state.search = '';
  $('#heroSearch').value = '';
  if ($('#activityTypeFilter')) $('#activityTypeFilter').value = 'All';
  $$('.filter-chip').forEach(chip => chip.classList.toggle('active', chip.dataset.filter === filter));
  $$('.vibe-tile').forEach(tile => tile.classList.toggle('is-selected', tile.dataset.vibeFilter === filter));
  renderChallenges();
  if (shouldScroll) $('#explore').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

$$('.filter-chip').forEach(chip => chip.addEventListener('click', () => {
  applyChallengeFilter(chip.dataset.filter);
}));
$$('.vibe-tile').forEach(tile => tile.addEventListener('click', () => {
  applyChallengeFilter(tile.dataset.vibeFilter, true);
}));
$('#activityTypeFilter')?.addEventListener('change', event => {
  state.activityType = event.target.value || 'All';
  renderChallenges();
});

function searchChallenges() {
  state.search = $('#heroSearch').value.trim();
  state.filter = 'All';
  state.activityType = 'All';
  if ($('#activityTypeFilter')) $('#activityTypeFilter').value = 'All';
  $$('.filter-chip').forEach(chip => chip.classList.toggle('active', chip.dataset.filter === 'All'));
  $$('.vibe-tile').forEach(tile => tile.classList.remove('is-selected'));
  renderChallenges();
  $('#explore').scrollIntoView({ behavior: 'smooth', block: 'start' });
}
$$('[data-quick-search]').forEach(button => button.addEventListener('click', () => {
  const term = button.dataset.quickSearch;
  const category = term === 'coding' ? 'Tech' : (term === 'creative' ? 'Creative' : 'Social');
  applyChallengeFilter(category, true);
}));
$('#heroSearchButton').addEventListener('click', searchChallenges);
$('#heroSearch').addEventListener('keydown', event => { if (event.key === 'Enter') searchChallenges(); });
$('#heroMuseButton').addEventListener('click', () => { $('#muse').scrollIntoView({ behavior: 'smooth', block: 'center' }); runMuse(); });
$('#openMuseButton').addEventListener('click', () => { $('#muse').scrollIntoView({ behavior: 'smooth', block: 'center' }); runMuse(); });
$('#museButton').addEventListener('click', runMuse);
$('#weeklyQuestButton')?.addEventListener('click', () => {
  if (state.weeklyChallenge) openChallengeDetails(state.weeklyChallenge.id);
});

$('#challengeReportForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!requireLogin() || !state.selectedChallenge) return;
  const button = $('#challengeReportForm button[type="submit"]');
  button.disabled = true;
  try {
    const result = await api(`/api/challenges/${state.selectedChallenge.id}/report`, { method: 'POST', body: { reason: $('#reportReason').value, details: $('#reportDetails').value.trim() } });
    $('#reportMessage').textContent = result.message;
    $('#reportDetails').value = '';
  } catch (error) { $('#reportMessage').textContent = error.message; }
  finally { button.disabled = false; }
});

$('#finalSubmitForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const id = Number($('#finalSubmitChallengeId').value);
  const button = $('#finalSubmitForm button[type="submit"]');
  button.disabled = true;
  try {
    const result = await api(`/api/challenges/${id}/submit`, { method: 'POST', body: { note: $('#finalSubmitNote').value.trim(), proof_url: $('#finalSubmitProof').value.trim() } });
    closeModal('finalSubmitModal');
    toast(result.message);
    await refreshPersonal();
  } catch (error) { $('#finalSubmitMessage').textContent = error.message; }
  finally { button.disabled = false; }
});

$('#profileForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('#profileForm button[type="submit"]');
  button.disabled = true;
  try {
    const result = await api('/api/profile', { method: 'POST', body: {
      department: $('#profileDepartment').value.trim(), study_year: $('#profileYear').value,
      bio: $('#profileBio').value.trim(), interests: $('#profileInterests').value.trim(),
      profile_public: $('#profilePublic').checked
    }});
    state.user = result.user; updateHeader();
    $('#profileMessage').textContent = result.message;
    await refreshPersonal(); await refreshCommunity();
  } catch (error) { $('#profileMessage').textContent = error.message; }
  finally { button.disabled = false; }
});

$('#peerKudosForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  if (!state.selectedTeam) return;
  const button = $('#peerKudosForm button[type="submit"]');
  button.disabled = true;
  try {
    const result = await api(`/api/teams/${state.selectedTeam.id}/kudos`, { method: 'POST', body: {
      to_user_id: $('#kudosRecipient').value, message: $('#kudosMessage').value.trim()
    }});
    $('#kudosMessageStatus').textContent = result.message;
    $('#kudosMessage').value = '';
    if (result.badge_awarded) toast('A Community Spark badge was awarded! ♡');
  } catch (error) { $('#kudosMessageStatus').textContent = error.message; }
  finally { button.disabled = false; }
});

$('#checkinForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const id = Number($('#checkinChallengeId').value);
  const submit = $('#checkinForm button[type="submit"]');
  submit.disabled = true;
  try {
    const result = await api(`/api/challenges/${id}/checkin`, {
      method: 'POST',
      body: { note: $('#checkinNote').value.trim(), proof_url: $('#checkinProof').value.trim() }
    });
    closeModal('checkinModal');
    toast(result.status === 'ready_to_submit' ? 'Daily steps complete! Submit your final work for review.' : `Check-in saved · ${result.progress}/${result.duration_days} days`);
    if (result.new_badges?.length) window.setTimeout(() => toast(`New badge earned: ${result.new_badges.join(', ')} ✦`), 900);
    await refreshPersonal();
    await refreshCommunity();
  } catch (error) { $('#checkinMessage').textContent = error.message; }
  finally { submit.disabled = false; }
});

$('#createQuestButton').addEventListener('click', () => {
  if (!requireLogin()) return;
  $('#createQuestMessage').textContent = '';
  openModal('createQuestModal');
});
$('#createQuestForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('#createQuestForm button[type="submit"]');
  button.disabled = true;
  try {
    const result = await api('/api/challenges/create', {
      method: 'POST',
      body: {
        title: $('#newQuestTitle').value.trim(), category: $('#newQuestCategory').value, activity_type: $('#newQuestType').value,
        duration_days: $('#newQuestDuration').value, team_allowed: $('#newQuestTeam').value === 'team',
        description: $('#newQuestDescription').value.trim()
      }
    });
    closeModal('createQuestModal');
    $('#createQuestForm').reset();
    await refreshPersonal();
    toast(result.message);
    $('#explore').scrollIntoView({ behavior: 'smooth' });
  } catch (error) { $('#createQuestMessage').textContent = error.message; }
  finally { button.disabled = false; }
});

$('#createTeamButton').addEventListener('click', () => {
  if (!requireLogin()) return;
  if (!state.myQuests.length) { toast('Join an active quest first, then you can start a squad for it.'); $('#explore').scrollIntoView({ behavior: 'smooth' }); return; }
  const count = populateTeamChallengeSelect();
  if (!count) { toast('You have no active quests to team up around yet.'); return; }
  $('#createTeamMessage').textContent = '';
  openModal('createTeamModal');
});
$('#createTeamForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = $('#createTeamForm button[type="submit"]');
  button.disabled = true;
  try {
    const result = await api('/api/teams', {
      method: 'POST', body: {
        name: $('#teamName').value.trim(), challenge_id: $('#teamChallenge').value,
        description: $('#teamDescription').value.trim()
      }
    });
    closeModal('createTeamModal');
    $('#createTeamForm').reset();
    await refreshPersonal();
    await refreshCommunity();
    toast(result.message);
    if (result.new_badges?.length) window.setTimeout(() => toast('Badge earned: Squad Star ✧'), 800);
  } catch (error) { $('#createTeamMessage').textContent = error.message; }
  finally { button.disabled = false; }
});

// Keep the desktop navigation's active marker in sync with the visible section.
if ('IntersectionObserver' in window) {
  const navLinks = $$('.main-nav a');
  const observedSections = ['explore', 'how-it-works', 'squads', 'your-space']
    .map(id => document.getElementById(id)).filter(Boolean);
  const sectionObserver = new IntersectionObserver(entries => {
    const visible = entries.filter(entry => entry.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    navLinks.forEach(link => link.classList.toggle('active', link.getAttribute('href') === `#${visible.target.id}`));
  }, { rootMargin: '-24% 0px -58% 0px', threshold: [0, .15, .35, .6] });
  observedSections.forEach(section => sectionObserver.observe(section));
}

const mobileMenuToggle = $('#mobileMenuToggle');
const mobileMenu = $('#mobileMenu');
if (mobileMenuToggle && mobileMenu) {
  mobileMenuToggle.addEventListener('click', () => {
    const isOpen = mobileMenu.classList.toggle('open');
    mobileMenuToggle.classList.toggle('is-open', isOpen);
    mobileMenuToggle.setAttribute('aria-expanded', String(isOpen));
    mobileMenuToggle.setAttribute('aria-label', isOpen ? 'Close navigation' : 'Open navigation');
  });
  $$('.mobile-menu a').forEach(link => link.addEventListener('click', () => {
    mobileMenu.classList.remove('open');
    mobileMenuToggle.classList.remove('is-open');
    mobileMenuToggle.setAttribute('aria-expanded', 'false');
    mobileMenuToggle.setAttribute('aria-label', 'Open navigation');
  }));
  document.addEventListener('click', event => {
    if (!mobileMenu.contains(event.target) && !mobileMenuToggle.contains(event.target)) {
      mobileMenu.classList.remove('open');
      mobileMenuToggle.classList.remove('is-open');
      mobileMenuToggle.setAttribute('aria-expanded', 'false');
      mobileMenuToggle.setAttribute('aria-label', 'Open navigation');
    }
  });
}

$('#year').textContent = new Date().getFullYear();
refreshAll();
