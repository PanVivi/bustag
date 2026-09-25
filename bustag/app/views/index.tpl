% rebase('base.tpl', title='推荐', path=path, msg=msg)
% curr_page = page_info[2]
<div class="container page-wide">
% if filter_value:
 <div class="alert alert-info py-2">
  当前筛选：{{filter_label}} · {{filter_value}}
  <a class="float-right" href="{{clear_url}}">清除筛选</a>
 </div>
% end
 <div class="row py-3">
	<div class="col-12">
		<ul class="nav nav-tabs">
		<li class="nav-item">
			<a class="nav-link {{'active' if like==1 else ''}}" href="?like=1">喜欢</a>
		</li>
		<li class="nav-item">
			<a class="nav-link {{'' if like==1 else 'active'}}" href="?like=0">不喜欢</a>
		</li>
		</ul>
	</div>
</div>
<div class="item-grid">
% i = 1
%for item in items:
% details = v2_items.get(item.fanhao)
% actor_states = {actor['name']: actor['state'] for actor in details['actors']} if details else {}
% actor_ids = {actor['name']: actor['actor_id'] for actor in details['actors']} if details else {}
<article id="form-{{i}}" class="tag-card">
	<img class="img-fluid img-thumbnail coverimg" src="{{poster_src(item.cover_img_url)}}" alt="{{item.fanhao}}">
	<div class="tag-body">
		<div class="small text-muted">id: {{item.id}}</div>
		<div class="small text-muted">发行日期: {{item.release_date}}</div>
		<div class="small text-muted">添加日期: {{item.add_date}}</div>
		<div class="tag-code-row">
			<h6 class="tag-fanhao">{{item.fanhao}}</h6>
% if details:
			<div class="v2-scoreline small">
% if details['model_current']:
				<span class="badge badge-info">匹配分数 {{'%.3f' % details['match_score']}}</span>
% else:
				<span class="badge badge-secondary">模型待训练或重评分</span>
% end
			</div>
% end
		</div>
		<a class="tag-title" href="{{item.url}}" target="_blank">{{item.title}}</a>
		<div class="tag-badges">
		% for t in item.tags_dict['genre']:
			<a class="badge badge-primary" href="{{tag_url('genre', t)}}">{{t}}</a>
		% end
		</div>
		<div class="tag-badges">
		% for t in item.tags_dict['star']:
% actor_state = actor_states.get(t, 'pending')
% actor_state_label = {'like': '喜欢', 'pending': '待确认', 'dislike': '不喜欢'}.get(actor_state, '待确认')
			<div class="actor-tag-item">
				<a class="badge badge-{{'warning' if actor_state == 'like' else 'danger' if actor_state == 'dislike' else 'secondary'}} actor-state-badge" data-actor-id="{{actor_ids.get(t, '')}}" data-actor-state="{{actor_state}}" title="演员偏好：{{actor_state_label}}" aria-label="{{t}}，演员偏好：{{actor_state_label}}" href="{{tag_url('star', t)}}">{{t}}</a>
% if actor_state == 'pending' and actor_ids.get(t):
				<form class="actor-quick-form" data-actor-id="{{actor_ids.get(t)}}" method="post" action="/v2/actor/{{actor_ids.get(t)}}">
					<input type="hidden" name="csrf" value="{{csrf}}">
					<input type="hidden" name="return_to" value="{{return_to}}#form-{{i}}">
					<button type="submit" class="actor-quick-btn actor-quick-like" name="state" value="like" title="喜欢 {{t}}" aria-label="喜欢 {{t}}">😍</button>
					<button type="submit" class="actor-quick-btn actor-quick-dislike" name="state" value="dislike" title="不喜欢 {{t}}" aria-label="不喜欢 {{t}}">😱</button>
					<span class="actor-quick-status sr-only" role="status" aria-live="polite"></span>
				</form>
% end
			</div>
		% end
		</div>
		<div class="tag-actions">
			<form action="/correct/{{item.fanhao}}{{query_url(curr_page)}}" method="post">
				<input type="hidden" name="formid" value="form-{{i}}">
				<button type="submit" name="submit" class="btn btn-primary btn-sm" value="1">正确</button>
				<button type="submit" name="submit" class="btn btn-danger btn-sm" value="0">错误</button>
			</form>
		</div>
% if details and details['actors']:
		<details class="v2-card-tools v2-actor-tools">
			<summary>演员偏好（{{len(details['actors'])}}）</summary>
			<div class="small text-muted mt-2">按演员独立记录偏好，不会更改本片标签或喜欢/不喜欢打标。</div>
% for actor in details['actors']:
			<form class="v2-control-row v2-actor-row" data-actor-id="{{actor['actor_id']}}" method="post" action="/v2/actor/{{actor['actor_id']}}">
				<input type="hidden" name="csrf" value="{{csrf}}">
				<input type="hidden" name="return_to" value="{{return_to}}#form-{{i}}">
				<span class="v2-actor-name">{{actor['name']}}</span>
				<div class="v2-actor-buttons">
% for value, label, button_class in [('like','喜欢','btn-primary'),('dislike','不喜欢','btn-danger'),('pending','待确认','btn-secondary')]:
					<button type="submit" name="state" value="{{value}}" class="btn {{button_class}} btn-sm {{'active' if actor['state']==value else ''}}" aria-pressed="{{'true' if actor['state']==value else 'false'}}">{{label}}</button>
% end
				</div>
				<span class="v2-actor-save-status small text-muted" role="status" aria-live="polite"></span>
			</form>
% end
		</details>
% end
	</div>
</article>
% i = i + 1
%end
</div>
% include('pagination.tpl', page_info=page_info)
</div>
