% rebase('base.tpl', title='打标', path=path)
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
			<a class="nav-link {{'active' if like is None else ''}}" href="?">未打标的</a>
		</li>
		<li class="nav-item">
			<a class="nav-link {{'active' if like==1 else ''}}" href="?like=1">喜欢</a>
		</li>
		<li class="nav-item">
			<a class="nav-link {{'active' if like==0 else ''}}" href="?like=0">不喜欢</a>
		</li>
		</ul>
	</div>
</div>
<p class="small text-muted mb-2">匹配分数仅用于相对排序，不是喜欢概率；缺失标签不代表不喜欢。</p>
<div class="item-grid">
% i = 1
%for item in items:
% details = v2_items.get(item.fanhao)
<article id="form-{{i}}" class="tag-card">
	<img class="img-fluid img-thumbnail coverimg" src="{{poster_src(item.cover_img_url)}}" alt="{{item.fanhao}}">
	<div class="tag-body">
		<div class="small text-muted">id: {{item.id}}</div>
		<div class="small text-muted">发行日期: {{item.release_date}}</div>
		<div class="small text-muted">添加日期: {{item.add_date}}</div>
		<h6 class="tag-fanhao">{{item.fanhao}}</h6>
		<a class="tag-title" href="{{item.url}}" target="_blank">{{item.title}}</a>
		<div class="tag-badges">
		% for t in item.tags_dict['genre']:
			<a class="badge badge-primary" href="{{tag_url('genre', t)}}">{{t}}</a>
		% end
		</div>
		<div class="tag-badges">
		% for t in item.tags_dict['star']:
			<a class="badge badge-warning" href="{{tag_url('star', t)}}">{{t}}</a>
		% end
		</div>
		<div class="tag-actions">
			<form action="/tag/{{item.fanhao}}{{query_url(curr_page)}}" method="post">
				<input type="hidden" name="formid" value="form-{{i}}">
% if like is None or like == 0:
				<button type="submit" name="submit" class="btn btn-primary btn-sm" value="1">喜欢</button>
% end
% if like is None or like == 1:
				<button type="submit" name="submit" class="btn btn-danger btn-sm" value="0">不喜欢</button>
% end
			</form>
		</div>
% if details:
		<div class="v2-scoreline small">
% if details['model_current']:
			<span class="badge badge-info">匹配分数 {{'%.3f' % details['match_score']}}</span>
			<span class="text-muted ml-1">模型匹配分数 {{'%.3f' % details['model_score']}}</span>
% else:
			<span class="badge badge-secondary">模型待训练或重评分</span>
% end
		</div>
% if details['actors'] or details['tags']:
		<details class="v2-card-tools">
			<summary>演员偏好与标签纠错</summary>
% if details['actors']:
			<div class="small text-muted mt-2">本片演员人工状态</div>
% for actor in details['actors']:
			<form class="v2-control-row" method="post" action="/v2/actor/{{actor['actor_id']}}">
				<input type="hidden" name="csrf" value="{{csrf}}">
				<input type="hidden" name="return_to" value="{{return_to}}#form-{{i}}">
				<label for="actor-{{i}}-{{actor['actor_id']}}">{{actor['name']}}</label>
				<select id="actor-{{i}}-{{actor['actor_id']}}" name="state" class="custom-select custom-select-sm">
% for value, label in [('like','喜欢'),('dislike','不喜欢'),('pending','待确认')]:
					<option value="{{value}}" {{'selected' if actor['state']==value else ''}}>{{label}}</option>
% end
				</select>
				<button type="submit" class="btn btn-outline-secondary btn-sm">保存</button>
			</form>
% end
% end
% if details['tags']:
			<div class="small text-muted mt-2">本片标签人工纠错</div>
% for tag in details['tags']:
			<form class="v2-control-row" method="post" action="/v2/tag/{{details['work_id']}}/{{tag['tag_id']}}">
				<input type="hidden" name="csrf" value="{{csrf}}">
				<input type="hidden" name="return_to" value="{{return_to}}#form-{{i}}">
				<span>{{tag['category']}} / {{tag['name']}}</span>
				<span class="badge badge-{{'success' if tag['enabled'] else 'secondary'}}">{{'采用' if tag['enabled'] else '已排除'}}</span>
				<button type="submit" name="enabled" value="{{'0' if tag['enabled'] else '1'}}" class="btn btn-outline-secondary btn-sm">{{'排除误标' if tag['enabled'] else '恢复标签'}}</button>
			</form>
% end
% end
		</details>
% end
% end
	</div>
</article>
% i = i + 1
%end
</div>
% include('pagination.tpl', page_info=page_info)
</div>
