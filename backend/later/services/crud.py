"""Generic tenant-scoped CRUD endpoints for simple collections."""
import re

from flask import request, jsonify, abort

from . import tenancy as t
from .security import api


def register_crud(bp, name, area, module=None, search=(), filters=(), prepare=None, after_save=None,
                  number=None, sort=("created_at", -1), protect_delete=None):
    """
    prepare(data, existing) -> data   : validate / compute fields before save
    after_save(doc, created)          : side-effects after save
    number=("INV", "invoice")         : auto-number field `number` on create
    """
    base = f"/{name}"

    def list_items():
        q = {}
        text = request.args.get("q")
        if text and search:
            rx = {"$regex": re.escape(text), "$options": "i"}
            q["$or"] = [{f: rx} for f in search]
        for f in filters:
            v = request.args.get(f)
            if v not in (None, ""):
                q[f] = v
        limit = min(int(request.args.get("limit", 500)), 1000)
        docs = t.find(name, q, sort=[sort], limit=limit)
        return jsonify([t.out(d) for d in docs])

    def get_item(_id):
        return jsonify(t.out(t.get(name, _id)))

    def create_item():
        data = request.get_json(force=True) or {}
        if prepare:
            data = prepare(data, None)
        if number and not data.get("number"):
            data["number"] = t.next_number(number[1], number[0])
        doc = t.insert(name, data)
        if after_save:
            after_save(doc, True)
        return jsonify(t.out(doc)), 201

    def update_item(_id):
        existing = t.get(name, _id)
        data = request.get_json(force=True) or {}
        if prepare:
            data = prepare({**{k: v for k, v in existing.items() if k != "_id"}, **data}, existing)
        doc = t.update(name, _id, data)
        if after_save:
            after_save(doc, False)
        return jsonify(t.out(doc))

    def delete_item(_id):
        if protect_delete:
            reason = protect_delete(t.get(name, _id))
            if reason:
                abort(409, reason)
        t.delete(name, _id)
        return jsonify({"ok": True})

    deco = api(area, module=module)
    bp.add_url_rule(base, f"{name}_list", deco(list_items), methods=["GET"])
    bp.add_url_rule(base, f"{name}_create", deco(create_item), methods=["POST"])
    bp.add_url_rule(f"{base}/<_id>", f"{name}_get", deco(get_item), methods=["GET"])
    bp.add_url_rule(f"{base}/<_id>", f"{name}_update", deco(update_item), methods=["PUT", "PATCH"])
    bp.add_url_rule(f"{base}/<_id>", f"{name}_delete", deco(delete_item), methods=["DELETE"])


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default
