"""GitHub Actions entry point: decides what to do on each run."""
import datetime as dt
import glob
import json
import os
import sys
import time
import traceback

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)


def write_secrets():
    """config.ini aur YouTube token GitHub Secrets se banao (repo mein kabhi save nahi hote)."""
    cfg = os.environ.get("CONFIG_INI", "").strip()
    if not cfg:
        sys.exit("CONFIG_INI secret khali hai - GitHub Settings > Secrets mein daalein")
    open(os.path.join(ROOT, "config.ini"), "w", encoding="utf-8").write(cfg + "\n")
    tok = os.environ.get("YOUTUBE_TOKEN", "").strip()
    if tok:
        open(os.path.join(ROOT, "youtube_token.json"), "w", encoding="utf-8").write(tok)


def prune(days=10):
    """posts/ mein 10 din se purani files hatao taaki repo chhota rahe."""
    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    for f in glob.glob(os.path.join(ROOT, "posts", "*")):
        name = os.path.basename(f)
        if name[:10] < cutoff and name[:4].isdigit():
            os.remove(f)
        if name.startswith("_"):
            os.remove(f)


def main():
    write_secrets()
    import main as m  # noqa: E402  (config.ini ke baad import)

    task = (sys.argv[1] if len(sys.argv) > 1 else "").strip() or "auto"
    sched = os.environ.get("SCHEDULE", "")
    if task == "auto":
        task = {"30 1 * * *": "generate", "30 2 * * *": "generate",
                "30 15 * * *": "performance"}.get(sched, "publish")
    m.log(f"[github] task={task} schedule={sched or '-'}")

    ok = True
    try:
        if task == "generate":
            m.cmd_generate()
        elif task == "generate_now":
            m.cmd_generate(force=True)
        elif task == "performance":
            m.cmd_performance()
        elif task == "sample_video":
            parts = m.parse_script(os.environ.get("SCRIPT", ""))
            out = os.path.join(m.OUT, "sample_" + time.strftime("%Y-%m-%d_%H%M") + ".mp4")
            m.make_free_video(parts, out, "")
            m.log(f"Sample video ban gaya: {out}")
            return
        elif task == "test":
            m.cmd_test()
            return
        # har run ke aakhir mein: dashboard request + approved posts
        if task in ("generate", "generate_now", "performance", "publish"):
            m.cmd_publish()
    except Exception as e:
        ok = False
        m.log(f"ERROR ({task}): {e}\n{traceback.format_exc()}")
        kind = "generate" if task.startswith("generate") else task
        m.heartbeat(kind, False, f"{type(e).__name__}: {e}")
    finally:
        prune()
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
