#!/usr/bin/env python3
"""Minimal MCP (streamable HTTP) client for the Fusion MCP server.

  mcp_call.py tools                      # list tools (name, description, input schema)
  mcp_call.py call TOOL '{"arg": 1}'     # call a tool with JSON arguments
  mcp_call.py raw METHOD '{...params}'   # any JSON-RPC method
  mcp_call.py script FILE [--include LIB ...] [--ro] [KEY=VALUE ...]
                                         # run a Fusion API script (must define run(context));
                                         # each __KEY__ in FILE is replaced by VALUE

URL defaults to http://127.0.0.1:27182/mcp (override with FUSION_MCP_URL).
"""
import json
import os
import sys
import urllib.request

URL = os.environ.get('FUSION_MCP_URL', 'http://127.0.0.1:27182/mcp')
PROTOCOL = '2025-06-18'


class Session:
    def __init__(self, url=URL):
        self.url = url
        self.sid = None
        self.next_id = 1
        init = self.request('initialize', {
            'protocolVersion': PROTOCOL,
            'capabilities': {},
            'clientInfo': {'name': 'mcp_call', 'version': '0.1'},
        })
        self.server_info = init
        self.notify('notifications/initialized')

    def _post(self, payload, timeout=1800):
        req = urllib.request.Request(self.url, data=json.dumps(payload).encode(), method='POST')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Accept', 'application/json, text/event-stream')
        if self.sid:
            req.add_header('Mcp-Session-Id', self.sid)
            req.add_header('MCP-Protocol-Version', PROTOCOL)
        resp = urllib.request.urlopen(req, timeout=timeout)
        self.sid = resp.headers.get('Mcp-Session-Id', self.sid)
        ctype = resp.headers.get('Content-Type', '')
        body = resp.read().decode('utf-8', 'replace')
        if not body.strip():
            return []
        if 'text/event-stream' in ctype:
            msgs = []
            for block in body.split('\n\n'):
                data = '\n'.join(l[5:].lstrip() for l in block.splitlines() if l.startswith('data:'))
                if data:
                    msgs.append(json.loads(data))
            return msgs
        parsed = json.loads(body)
        return parsed if isinstance(parsed, list) else [parsed]

    def request(self, method, params=None):
        rid = self.next_id
        self.next_id += 1
        msg = {'jsonrpc': '2.0', 'id': rid, 'method': method}
        if params is not None:
            msg['params'] = params
        for reply in self._post(msg):
            if reply.get('id') == rid:
                if 'error' in reply:
                    raise RuntimeError(json.dumps(reply['error'], indent=1))
                return reply.get('result')
        raise RuntimeError('no reply for request %d' % rid)

    def notify(self, method, params=None):
        msg = {'jsonrpc': '2.0', 'method': method}
        if params is not None:
            msg['params'] = params
        self._post(msg)

    def list_tools(self):
        tools, cursor = [], None
        while True:
            res = self.request('tools/list', {'cursor': cursor} if cursor else {})
            tools += res.get('tools', [])
            cursor = res.get('nextCursor')
            if not cursor:
                return tools

    def call(self, name, arguments=None):
        return self.request('tools/call', {'name': name, 'arguments': arguments or {}})


def main(argv):
    s = Session()
    cmd = argv[1] if len(argv) > 1 else 'tools'
    if cmd == 'tools':
        print(json.dumps({'server': s.server_info, 'tools': s.list_tools()}, indent=1))
    elif cmd == 'call':
        res = s.call(argv[2], json.loads(argv[3]) if len(argv) > 3 else {})
        for item in res.get('content', []):
            if item.get('type') == 'text':
                print(item['text'])
            else:
                print(json.dumps(item)[:2000])
        if res.get('structuredContent') is not None:
            print(json.dumps(res['structuredContent'], indent=1))
        if res.get('isError'):
            return 1
    elif cmd == 'script':
        source = open(argv[2], encoding='utf-8').read()
        read_only = False
        extras = argv[3:]
        while extras and extras[0] == '--include':
            # Prepend helper files; a later `def run` in FILE overrides any in the includes.
            source = open(extras[1], encoding='utf-8').read() + '\n\n' + source
            extras = extras[2:]
        for extra in extras:
            if extra == '--ro':
                read_only = True
            else:
                key, _, value = extra.partition('=')
                source = source.replace('__%s__' % key, value)
        obj = {'script': source}
        if read_only:
            obj['readOnly'] = True
        res = s.call('fusion_mcp_execute', {'featureType': 'script', 'object': obj})
        payload = res.get('structuredContent')
        if payload is None:
            text = ''.join(i.get('text', '') for i in res.get('content', []) if i.get('type') == 'text')
            try:
                payload = json.loads(text)
            except ValueError:
                payload = {'message': text}
        sys.stdout.write(payload.get('message', ''))
        if not payload.get('success', not res.get('isError')):
            sys.stderr.write(payload.get('error', json.dumps(payload)) + '\n')
            return 1
    elif cmd == 'raw':
        print(json.dumps(s.request(argv[2], json.loads(argv[3]) if len(argv) > 3 else {}), indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
