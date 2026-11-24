"""Maya-side implementations of the built-in tools.

The server never imports this file: it sends the source to Maya and calls one
of the functions there with ARGS (a dict) as its argument.
"""
import os

from maya import cmds

DEFAULT_CAMERAS = {"persp", "top", "front", "side"}
COUNTED_TYPES = (
    "joint",
    "mesh",
    "skinCluster",
    "blendShape",
    "dagPose",
    "nurbsCurve",
    "ikHandle",
    "constraint",
    "expression",
    "animCurve",
)
LIST_CAP = 50


def status(args):
    return {
        "maya_version": cmds.about(version=True),
        "batch": cmds.about(batch=True),
        "ui_language": cmds.about(uiLanguage=True),
        "pid": os.getpid(),
        "scene": cmds.file(query=True, sceneName=True) or None,
        "modified": cmds.file(query=True, modified=True),
    }


def scene_summary(args):
    selection = cmds.ls(selection=True) or []
    return {
        "scene": cmds.file(query=True, sceneName=True) or None,
        "modified": cmds.file(query=True, modified=True),
        "units": {
            "linear": cmds.currentUnit(query=True, linear=True),
            "angle": cmds.currentUnit(query=True, angle=True),
            "time": cmds.currentUnit(query=True, time=True),
        },
        "up_axis": cmds.upAxis(query=True, axis=True),
        "current_frame": cmds.currentTime(query=True),
        "playback_range": [
            cmds.playbackOptions(query=True, minTime=True),
            cmds.playbackOptions(query=True, maxTime=True),
        ],
        "top_level_nodes": [n for n in cmds.ls(assemblies=True) or [] if n not in DEFAULT_CAMERAS],
        "node_counts": {t: len(cmds.ls(type=t) or []) for t in COUNTED_TYPES},
        "references": cmds.file(query=True, reference=True) or [],
        "selection_count": len(selection),
        "selection": selection[:LIST_CAP],
    }


def list_nodes(args):
    kwargs = {"long": args["long_names"]}
    if args["node_type"]:
        kwargs["type"] = args["node_type"]
    nodes = cmds.ls(args["pattern"], **kwargs) or []
    limit = args["limit"]
    return {"count": len(nodes), "truncated": len(nodes) > limit, "nodes": nodes[:limit]}


def _connections(path, incoming):
    # listConnections(connections=True) returns [this.plug, other.plug, ...]
    flat = cmds.listConnections(
        path, source=incoming, destination=not incoming, plugs=True, connections=True
    ) or []
    pairs = zip(flat[0::2], flat[1::2])
    if incoming:
        return ["%s -> %s" % (other, mine) for mine, other in pairs][:LIST_CAP]
    return ["%s -> %s" % (mine, other) for mine, other in pairs][:LIST_CAP]


def node_info(args):
    matches = cmds.ls(args["node"], long=True) or []
    if not matches:
        raise ValueError("No node matches %r" % args["node"])
    if len(matches) > 1:
        raise ValueError("%r is ambiguous: %s" % (args["node"], ", ".join(matches[:10])))
    path = matches[0]
    info = {"name": path, "type": cmds.nodeType(path)}

    if cmds.objectType(path, isAType="dagNode"):
        parents = cmds.listRelatives(path, parent=True, fullPath=True) or []
        children = cmds.listRelatives(path, children=True, fullPath=True) or []
        info["parent"] = parents[0] if parents else None
        info["child_count"] = len(children)
        info["children"] = children[:LIST_CAP]
    if cmds.objectType(path, isAType="transform"):
        info["world_translation"] = cmds.xform(path, query=True, worldSpace=True, translation=True)

    names = (cmds.listAttr(path, keyable=True) or []) + (cmds.listAttr(path, channelBox=True) or [])
    if info["type"] == "joint":
        # not keyable, but what a rigger checks first
        names += ["jointOrientX", "jointOrientY", "jointOrientZ", "rotateOrder", "segmentScaleCompensate"]
    attributes = {}
    for name in names:
        try:
            attributes[name] = cmds.getAttr("%s.%s" % (path, name))
        except (RuntimeError, ValueError):
            pass  # compound or message attributes have no plain value
    info["attributes"] = attributes
    info["incoming"] = _connections(path, incoming=True)
    info["outgoing"] = _connections(path, incoming=False)
    return info


def capture_viewport(args):
    if cmds.about(batch=True):
        raise RuntimeError("Maya is running without a UI, so there is no viewport to capture")
    frame = args["frame"]
    if frame is None:
        frame = cmds.currentTime(query=True)
    path = cmds.playblast(
        frame=[frame],
        format="image",
        compression="png",
        completeFilename=args["path"],
        widthHeight=[args["width"], args["height"]],
        percent=100,
        quality=100,
        viewer=False,
        showOrnaments=args["show_ornaments"],
        offScreen=True,
        forceOverwrite=True,
    )
    _drop_alpha(path)
    return path


def _drop_alpha(path):
    # playblast writes alpha 0 wherever there is no geometry, so viewers show
    # the background as white instead of the viewport colour
    try:
        from PySide6.QtGui import QImage
    except ImportError:
        from PySide2.QtGui import QImage
    image = QImage(path)
    if image.isNull() or not image.hasAlphaChannel():
        return
    if not image.convertToFormat(QImage.Format_RGB888).save(path, "PNG"):
        raise RuntimeError("could not rewrite %s without its alpha channel" % path)
