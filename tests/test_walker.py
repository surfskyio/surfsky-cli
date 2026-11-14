import json
import shutil
import subprocess

import pytest

from surfsky_cli import snapshot

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="needs node")

# h1#title, a#link, input#pass[type=password], input#query: all visible, ids unique
HARNESS = r"""
const {script, args} = JSON.parse(require('fs').readFileSync(0, 'utf8'));
const element = (tag, id, props = {}) => ({
  tagName: tag.toUpperCase(), nodeType: 1, id, parentElement: null, innerText: props.text || '',
  type: props.type, value: props.value, href: props.href,
  getAttribute: () => null,
  getBoundingClientRect: () => ({width: 10, height: 10}),
  matches: () => !/^h[1-6]$/.test(tag),
});
const elements = [
  element('h1', 'title', {text: 'Sign in'}),
  element('a', 'link', {text: 'Help', href: 'https://e.test/help'}),
  element('input', 'pass', {type: 'password', value: 'hunter2'}),
  element('input', 'query', {type: 'text', value: 'lisbon'}),
];
globalThis.CSS = {escape: text => text};
globalThis.getComputedStyle = () => ({visibility: 'visible', display: 'block'});
globalThis.document = {
  documentElement: {},
  getElementById: () => null,
  querySelectorAll: selector => selector.startsWith('#')
    ? elements.filter(el => '#' + el.id === selector)
    : selector.includes('h1') ? elements : [],
};
console.log(JSON.stringify(eval(script)(...args)));
"""


def walk(*args):
    done = subprocess.run(
        ["node", "-e", HARNESS],
        input=json.dumps({"script": snapshot.SCRIPT, "args": args}),
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(done.stdout)


def test_a_ref_number_means_one_element_whatever_the_filter():
    every = {item["selector"]: item["ref"] for item in walk(500, False, None)["items"]}
    assert every == {"#title": 1, "#link": 2, "#pass": 3, "#query": 4}
    acted_on = {item["selector"]: item["ref"] for item in walk(500, True, None)["items"]}
    assert acted_on == {"#link": 2, "#pass": 3, "#query": 4}
    found = {item["selector"]: item["ref"] for item in walk(500, False, "help")["items"]}
    assert found == {"#link": 2}


def test_one_element_is_read_without_the_rest_of_the_page():
    data = walk(1, False, {"selector": "#link"})
    assert [(item["role"], item["name"]) for item in data["items"]] == [("link", "Help")]


def test_a_password_value_is_not_reported():
    items = {item["selector"]: item for item in walk(500, False, None)["items"]}
    assert items["#query"]["value"] == "lisbon"
    assert items["#pass"]["type"] == "password" and "value" not in items["#pass"]
