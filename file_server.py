import time
from datetime import datetime
import os
import re
import stat
import json
import mimetypes

from flask import Flask, make_response, request, session, render_template, send_file, Response
from flask.views import MethodView
from werkzeug import secure_filename
import humanize
import paramiko


app = Flask(__name__, static_url_path='/assets', static_folder='assets')
root = os.path.expanduser('~')

ignored = ['.bzr', '$RECYCLE.BIN', '.DAV', '.DS_Store', '.git', '.hg', '.htaccess', '.htpasswd', '.Spotlight-V100', '.svn', '__MACOSX', 'ehthumbs.db', 'robots.txt', 'Thumbs.db', 'thumbs.tps']
datatypes = {'audio': 'm4a,mp3,oga,ogg,webma,wav', 'archive': '7z,zip,rar,gz,tar', 'image': 'gif,ico,jpe,jpeg,jpg,png,svg,webp', 'pdf': 'pdf', 'quicktime': '3g2,3gp,3gp2,3gpp,mov,qt', 'source': 'atom,bat,bash,c,cmd,coffee,css,hml,js,json,java,less,markdown,md,php,pl,py,rb,rss,sass,scpt,swift,scss,sh,xml,yml,plist', 'text': 'txt', 'video': 'mp4,m4v,ogv,webm', 'website': 'htm,html,mhtm,mhtml,xhtm,xhtml'}
icontypes = {'fa-music': 'm4a,mp3,oga,ogg,webma,wav', 'fa-archive': '7z,zip,rar,gz,tar', 'fa-picture-o': 'gif,ico,jpe,jpeg,jpg,png,svg,webp', 'fa-file-text': 'pdf', 'fa-film': '3g2,3gp,3gp2,3gpp,mov,qt', 'fa-code': 'atom,plist,bat,bash,c,cmd,coffee,css,hml,js,json,java,less,markdown,md,php,pl,py,rb,rss,sass,scpt,swift,scss,sh,xml,yml', 'fa-file-text-o': 'txt', 'fa-film': 'mp4,m4v,ogv,webm', 'fa-globe': 'htm,html,mhtm,mhtml,xhtm,xhtml'}

@app.template_filter('size_fmt')
def size_fmt(size):
    return humanize.naturalsize(size)

@app.template_filter('time_fmt')
def time_desc(timestamp):
    mdate = datetime.fromtimestamp(timestamp)
    str = mdate.strftime('%Y-%m-%d %H:%M:%S')
    return str

@app.template_filter('data_fmt')
def data_fmt(filename):
    t = 'unknown'
    for type, exts in datatypes.items():
        if filename.split('.')[-1] in exts:
            t = type
    return t

@app.template_filter('icon_fmt')
def icon_fmt(filename):
    i = 'fa-file-o'
    for icon, exts in icontypes.items():
        if filename.split('.')[-1] in exts:
            i = icon
    return i

@app.template_filter('humanize')
def time_humanize(timestamp):
    mdate = datetime.fromtimestamp(timestamp)
    return humanize.naturaltime(mdate)

def get_type(mode):
    if stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
        type = 'dir'
    else:
        type = 'file'
    return type

def partial_response(fd, mimetype, file_size, filename=None, start=None, end=None):
    if start is None:
        start = 0
    if end is None:
        end = file_size - 1
    end = min(end, file_size - 1 )
    length = end - start + 1

    def generate_large_file(fd,start,length):
        fd.seek(start)
        content = bytes()
        content_len = 0
        step = 2**20
        while length > content_len:
            if length - content_len < step:
                read_length = length - content_len
            else:
                read_length = step
            content += fd.read(read_length)
            content_len += read_length
            yield content

    response = Response(
        generate_large_file(fd,start,length),
        206,
        mimetype=mimetype,
        direct_passthrough=True,
    )
    response.headers.add(
        'Content-Range', 'bytes {0}-{1}/{2}'.format(
            start, end, file_size,
        ),
    )
    if filename:
        response.headers.add(
            'Content-Disposition', 'attachment; filename={0}'.format(filename)
        )
    return response

def file_response(fd, mimetype, file_size,filename=None):
    def generate_large_file(fd,file_size):
        fd.seek(0)
        content = bytes()
        content_len = 0
        step = 2**20
        while file_size > content_len:
            if file_size - content_len < step:
                read_length = file_size - content_len
            else:
                read_length = step
            content += fd.read(read_length)
            content_len += read_length
            yield content

    response = Response(
        generate_large_file(fd,file_size),
        200,
        mimetype=mimetype,
        direct_passthrough=True,
    )
    response.headers.add(
        'Content-Length', file_size
    )
    response.headers.add(
        'Cache-Control', 'public, max-age=43200'
    )
    if filename:
        response.headers.add(
            'Content-Disposition', 'attachment; filename={0}'.format(filename)
        )
    return response

def get_range(request):
    range = request.headers.get('Range')
    m = re.match('bytes=(?P<start>\d+)-(?P<end>\d+)?', range)
    if m:
        start = m.group('start')
        end = m.group('end')
        start = int(start)
        if end is not None:
            end = int(end)
        return start, end
    else:
        return 0, None

class PathView(MethodView):
    def get(self, p=''):
        username = 'test'
        hide_dotfile = request.args.get('hide-dotfile', request.cookies.get('hide-dotfile', 'no'))
        side = p[:p.find('/')]
        res = None
        if side == username:
            path = os.path.join(root,username, p[p.find('/')+1:])
            try:
                os.stat(os.path.join(root,username))
            except:
                os.mkdir(os.path.join(root,username))
            try:
                current_stat = os.stat(path)
            except:
                res = make_response('Not found', 404)
            else:
                current_open = open
                current_listdir = os.listdir
                current_os_stat = os.stat
        elif side == 'servers':
            fullpath = p[p.find('/')+1:]
            if fullpath == '':
                contents = [
                        {'name':'127.0.0.1','mtime':time.time(),'type':'dir'},
                ]
            else:
                address = fullpath[:fullpath.find('/')]
                path = os.path.join('.', fullpath[fullpath.find('/')+1:])
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(address)
                sftp = ssh.open_sftp()
                try:
                    current_stat = sftp.lstat(path)
                except:
                    res = make_response('Not found', 404)
                else:
                    current_open = sftp.open
                    current_listdir = sftp.listdir
                    current_os_stat = sftp.lstat
        else:
            contents = [
                    {'name':username,'mtime':time.time(),'type':'dir'},
                    {'name':'servers','mtime':time.time(),'type':'dir'},
            ]
        if p in ('','servers/'):
            total = {'size': 0, 'dir': 0, 'file': 0}
            page = render_template('index.html', path=p, contents=contents, total=total, hide_dotfile=hide_dotfile)
            res = make_response(page, 200)
        elif side in (username,'servers') and not res:
            if stat.S_ISDIR(current_stat.st_mode):
                contents = []
                total = {'size': 0, 'dir': 0, 'file': 0}
                for filename in current_listdir(path):
                    if filename in ignored:
                        continue
                    if hide_dotfile == 'yes' and filename[0] == '.':
                        continue
                    filepath = os.path.join(path, filename)
                    stat_res = current_os_stat(filepath)
                    info = {}
                    info['name'] = filename
                    info['mtime'] = stat_res.st_mtime
                    ft = get_type(stat_res.st_mode)
                    info['type'] = ft
                    total[ft] += 1
                    sz = stat_res.st_size
                    info['size'] = sz
                    total['size'] += sz
                    contents.append(info)
                page = render_template('index.html', path=p, contents=contents, total=total, hide_dotfile=hide_dotfile)
                res = make_response(page, 200)
                res.set_cookie('hide-dotfile', hide_dotfile, max_age=16070400)
            elif stat.S_ISREG(current_stat.st_mode):
                current_fd = current_open(path,'rb')
                mimetype = mimetypes.guess_type(path)[0]
                filename = os.path.split(path)[-1]
                if 'Range' in request.headers:
                    start, end = get_range(request)
                    res = partial_response(current_fd,mimetype,current_stat.st_size,filename=filename,start=start,end=end)
                else:
                    res = file_response(current_fd,mimetype,current_stat.st_size,filename=filename)
        else:
            res = make_response('Not found', 404)
        return res

    def post(self, p=''):
        username = 'test'
        hide_dotfile = request.args.get('hide-dotfile', request.cookies.get('hide-dotfile', 'no'))
        side = p[:p.find('/')]
        not_real_path = False
        if side == username:
            path = os.path.join(root,username, p[p.find('/')+1:])
            try:
                current_stat = os.stat(path)
            except:
                res = make_response('Not found', 404)
            else:
                def filesave(fl,path,file_size=None):
                    fl.save(path)
                current_save = filesave
        elif side == 'servers':
            fullpath = p[p.find('/')+1:]
            if fullpath == '':
                not_real_path = True
            else:
                address = fullpath[:fullpath.find('/')]
                path = os.path.join('.', fullpath[fullpath.find('/')+1:])
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(address)
                sftp = ssh.open_sftp()
                try:
                    current_stat = sftp.lstat(path)
                except:
                    res = make_response('Not found', 404)
                else:
                    current_save = sftp.putfo
        else:
            not_real_path = True
        info = {}
        if not_real_path:
            info['status'] = 'error'
            info['msg'] = 'FORBIDDEN'
        elif stat.S_ISDIR(current_stat.st_mode):
            files = request.files.getlist('files[]')
            for file in files:
                try:
                    filename = secure_filename(file.filename)
                    current_save(file,os.path.join(path, filename))
                except Exception as e:
                    info['status'] = 'error'
                    info['msg'] = str(e)
                else:
                    info['status'] = 'success'
                    info['msg'] = 'File Saved'
        else:
            info['status'] = 'error'
            info['msg'] = 'Invalid Operation'
        res = make_response(json.JSONEncoder().encode(info), 200)
        res.headers.add('Content-type', 'application/json')
        return res

path_view = PathView.as_view('path_view')
app.add_url_rule('/', view_func=path_view)
app.add_url_rule('/<path:p>', view_func=path_view)

if __name__ == '__main__':
    app.run('0.0.0.0', 8000, threaded=True, debug=True)
