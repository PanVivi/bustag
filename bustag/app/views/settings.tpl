% rebase('base.tpl', title='设置', path=path, msg=msg, errmsg=errmsg)
<div class="container page-wide settings-page">
  <h4 class="mb-3">设置</h4>

  <form method="post" class="card p-3 mb-4">
    <h5>显示布局</h5>
    <p class="text-muted small mb-2">针对 2560×1440 宽屏：双排放大海报，文字和打标按钮放在海报正下方，宽度不超过海报。</p>
    <div class="form-check">
      <input class="form-check-input" type="radio" name="layout" id="layout-double" value="double" {{'checked' if layout=='double' else ''}}>
      <label class="form-check-label" for="layout-double">双排显示（推荐）</label>
    </div>
    <div class="form-check mb-3">
      <input class="form-check-input" type="radio" name="layout" id="layout-single" value="single" {{'checked' if layout=='single' else ''}}>
      <label class="form-check-label" for="layout-single">单排显示</label>
    </div>
    <button class="btn btn-primary" type="submit" name="submit" value="layout">保存布局</button>
  </form>

  <form method="post" class="card p-3 mb-4">
    <h5>自定义抓取</h5>
    <div class="form-group">
      <label>方式</label>
      <select class="form-control" name="fetch_type">
        <option value="fanhao">按番号</option>
        <option value="series">按番号抓取整个系列</option>
        <option value="star">按演员</option>
      </select>
    </div>
    <div class="form-group">
      <label>内容</label>
      <input class="form-control" type="text" name="fetch_query" placeholder="例如 NFDM-519、NFDM、或演员名">
    </div>
    <button class="btn btn-primary" type="submit" name="submit" value="fetch">加入抓取队列</button>
  </form>

  <form method="post" class="card p-3 mb-4">
    <h5>爬虫设置</h5>
    <div class="form-row">
      <div class="form-group col-md-4">
        <label>并发数</label>
        <input class="form-control" type="number" min="1" max="5" name="max_tasks" value="{{cfg['max_tasks']}}">
      </div>
      <div class="form-group col-md-4">
        <label>请求间隔（秒）</label>
        <input class="form-control" type="number" min="1" max="30" name="delay" value="{{cfg['delay']}}">
      </div>
      <div class="form-group col-md-4">
        <label>每轮数量</label>
        <input class="form-control" type="number" min="1" max="100" name="count" value="{{cfg['count']}}">
      </div>
      <div class="form-group col-md-4">
        <label>周期间隔（秒）</label>
        <input class="form-control" type="number" min="3600" name="interval" value="{{cfg['interval']}}">
      </div>
      <div class="form-group col-md-4">
        <label>每日总量</label>
        <input class="form-control" type="number" min="1" max="500" name="daily_limit" value="{{cfg['daily_limit']}}">
      </div>
    </div>
    <p class="small text-muted">当前默认保持慢速：并发 1、间隔 4 秒、每轮 20、12 小时一轮。周期间隔在下次调度重启后完全生效。</p>
    <button class="btn btn-primary" type="submit" name="submit" value="crawler">保存爬虫设置</button>
  </form>

  <div class="card p-3 mb-4">
    <h5>抓取队列</h5>
    <p class="text-muted small mb-2">实时显示当前任务与等待列表。自定义抓取会插到队头，当前这条抓完后立刻执行。</p>
    <div id="crawl-queue-meta" class="small text-muted mb-2">加载中…</div>
    <div id="crawl-queue-body" class="queue-window">等待队列数据</div>
  </div>
</div>
<script>
(function () {
  function esc(text) {
    var box = document.createElement('div');
    box.appendChild(document.createTextNode(String(text || '')));
    return box.innerHTML;
  }
  function line(item, tag) {
    if (!item) return '';
    var kind = item.kind === 'custom' ? '插队' : '常规';
    var extra = item.status ? (' · ' + item.status) : '';
    return '<div class="queue-item queue-' + tag + '">' +
      '<span class="queue-kind">[' + kind + ']</span> ' +
      esc(item.label || item.url) + extra +
      '</div>';
  }
  function paint(data) {
    var meta = document.getElementById('crawl-queue-meta');
    var body = document.getElementById('crawl-queue-body');
    if (!meta || !body) return;
    var pending = data.pending || [];
    meta.textContent = '更新 ' + (data.updated_at || '-') +
      ' · 今日已抓 ' + (data.day_count || 0) +
      ' · 等待 ' + pending.length + ' 条';
    var html = '';
    if (data.current) {
      html += '<div class="queue-section">正在抓取</div>' + line(data.current, 'current');
    } else {
      html += '<div class="queue-section">正在抓取</div><div class="queue-item">空闲</div>';
    }
    html += '<div class="queue-section">等待中（队头在上）</div>';
    if (!pending.length) {
      html += '<div class="queue-item">暂无等待</div>';
    } else {
      for (var i = 0; i < pending.length; i++) {
        html += line(pending[i], pending[i].kind === 'custom' ? 'custom' : 'pending');
      }
    }
    var recent = data.recent || [];
    html += '<div class="queue-section">最近完成</div>';
    if (!recent.length) {
      html += '<div class="queue-item">暂无</div>';
    } else {
      for (var j = 0; j < recent.length && j < 8; j++) {
        html += line(recent[j], 'recent');
      }
    }
    body.innerHTML = html;
  }
  function tick() {
    var xhr = new XMLHttpRequest();
    xhr.open('GET', '/queue.json');
    xhr.onload = function () {
      try { paint(JSON.parse(xhr.responseText)); } catch (err) {}
    };
    xhr.send();
  }
  setInterval(tick, 1500);
  tick();
})();
</script>
