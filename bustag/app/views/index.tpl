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
<form id="form-{{i}}" class="tag-card" action="/correct/{{item.fanhao}}{{query_url(curr_page)}}" method="post">
	<img class="img-fluid img-thumbnail coverimg" src="{{poster_src(item.cover_img_url)}}" alt="{{item.fanhao}}">
	<div class="tag-body">
		<div class="small text-muted">id: {{item.id}}</div>
		<div class="small text-muted">发行日期: {{item.release_date}}</div>
		<div class="small text-muted">添加日期: {{item.add_date}}</div>
		% if getattr(item, 'recommend_score', None) is not None:
        <div class="small"><span class="badge badge-success">匹配分数 {{int(round(item.recommend_score * 100))}}</span></div>
        % end
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
			<input type=hidden name="formid" value="form-{{i}}">
			<button type="submit" name="submit" class="btn btn-primary btn-sm" value="1">正确</button>
			<button type="submit" name="submit" class="btn btn-danger btn-sm" value="0">错误</button>
		</div>
	</div>
</form>
% i = i + 1
%end
</div>
% include('pagination.tpl', page_info=page_info)
</div>
