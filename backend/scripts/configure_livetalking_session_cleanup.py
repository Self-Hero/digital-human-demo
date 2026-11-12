"""Make LiveTalking reclaim disconnected WebRTC sessions reliably."""

from __future__ import annotations

import argparse
import py_compile
import shutil
from pathlib import Path


HANDLER_ANCHOR = '''        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            logger.info("Connection state is %s", pc.connectionState)
            if pc.connectionState in ("failed", "closed"):
                await pc.close()
                self.pcs.discard(pc)
                session_manager.remove_session(sessionid)
'''

PATCHED_HANDLER = '''        cleanup_started = False
        disconnect_cleanup_task = None

        async def cleanup_session():
            nonlocal cleanup_started
            if cleanup_started:
                return
            cleanup_started = True
            if pc.connectionState != "closed":
                await pc.close()
            self.pcs.discard(pc)
            session_manager.remove_session(sessionid)

        async def cleanup_after_disconnect():
            await asyncio.sleep(5)
            if pc.connectionState == "disconnected":
                logger.info(
                    "Connection remained disconnected; reclaiming session %s",
                    sessionid,
                )
                await cleanup_session()

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            nonlocal disconnect_cleanup_task
            logger.info("Connection state is %s", pc.connectionState)
            if pc.connectionState == "connected":
                if disconnect_cleanup_task is not None:
                    disconnect_cleanup_task.cancel()
                    disconnect_cleanup_task = None
            elif pc.connectionState == "disconnected":
                if disconnect_cleanup_task is None:
                    disconnect_cleanup_task = asyncio.create_task(
                        cleanup_after_disconnect()
                    )
            elif pc.connectionState in ("failed", "closed"):
                if disconnect_cleanup_task is not None:
                    disconnect_cleanup_task.cancel()
                    disconnect_cleanup_task = None
                await cleanup_session()
'''

MAX_SESSION_RESPONSE_ANCHOR = '''            return web.Response(
                content_type="application/json",
                text=json.dumps({"code": -1, "msg": str(e)}),
            )
'''

PATCHED_MAX_SESSION_RESPONSE = '''            return web.Response(
                status=409,
                content_type="application/json",
                text=json.dumps({"code": -1, "msg": str(e)}),
            )
'''

OFFER_ANCHOR = '''        logger.info('offer sessionid=%s', sessionid)

        pc = await self._create_pc_and_answer(
            session_manager.get_session(sessionid), sessionid, offer
        )

        return web.Response(
'''

PATCHED_OFFER = '''        logger.info('offer sessionid=%s', sessionid)

        try:
            pc = await self._create_pc_and_answer(
                session_manager.get_session(sessionid), sessionid, offer
            )
        except Exception:
            session_manager.remove_session(sessionid)
            raise

        return web.Response(
'''

APP_HANDLER_ANCHOR = '''async def whep(request):
    return await rtc_manager.handle_whep(request)

async def on_shutdown(app):
'''

PATCHED_APP_HANDLER = '''async def whep(request):
    return await rtc_manager.handle_whep(request)

async def close_session(request):
    sessionid = str(request.match_info.get("sessionid", "")).strip()
    existed = bool(sessionid and session_manager.has_session(sessionid))
    if existed:
        session_manager.remove_session(sessionid)
    return web.Response(
        status=200 if existed else 404,
        content_type="application/json",
        text=json.dumps({
            "code": 0 if existed else -1,
            "msg": "ok" if existed else "session not found",
        }),
    )

async def on_shutdown(app):
'''

APP_ROUTE_ANCHOR = '''    appasync.router.add_post("/offer", offer)
    appasync.router.add_get("/record/{sessionid}", download_record)
'''

PATCHED_APP_ROUTE = '''    appasync.router.add_post("/offer", offer)
    appasync.router.add_delete("/session/{sessionid}", close_session)
    appasync.router.add_get("/record/{sessionid}", download_record)
'''


def _replace_once(text: str, old: str, new: str, description: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"Expected one {description}, found {count}")
    return text.replace(old, new, 1)


def configure(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if (
        PATCHED_HANDLER in text
        and PATCHED_MAX_SESSION_RESPONSE in text
        and PATCHED_OFFER in text
    ):
        return "already configured"

    updated = text
    if PATCHED_HANDLER not in updated:
        updated = _replace_once(
            updated,
            HANDLER_ANCHOR,
            PATCHED_HANDLER,
            "WebRTC connection-state handler",
        )
    if PATCHED_MAX_SESSION_RESPONSE not in updated:
        updated = _replace_once(
            updated,
            MAX_SESSION_RESPONSE_ANCHOR,
            PATCHED_MAX_SESSION_RESPONSE,
            "maximum-session response",
        )
    if PATCHED_OFFER not in updated:
        updated = _replace_once(
            updated,
            OFFER_ANCHOR,
            PATCHED_OFFER,
            "WebRTC offer creation",
        )

    backup = source.with_suffix(source.suffix + ".before-session-cleanup")
    if not backup.exists():
        shutil.copy2(source, backup)
    source.write_text(updated, encoding="utf-8")
    try:
        py_compile.compile(str(source), doraise=True)
    except Exception:
        source.write_text(text, encoding="utf-8")
        raise
    return f"configured; backup: {backup}"


def configure_app(source: Path) -> str:
    text = source.read_text(encoding="utf-8")
    if PATCHED_APP_HANDLER in text and PATCHED_APP_ROUTE in text:
        return "already configured"

    updated = text
    if PATCHED_APP_HANDLER not in updated:
        updated = _replace_once(
            updated,
            APP_HANDLER_ANCHOR,
            PATCHED_APP_HANDLER,
            "session close handler",
        )
    if PATCHED_APP_ROUTE not in updated:
        updated = _replace_once(
            updated,
            APP_ROUTE_ANCHOR,
            PATCHED_APP_ROUTE,
            "session close route",
        )

    backup = source.with_suffix(source.suffix + ".before-session-cleanup")
    if not backup.exists():
        shutil.copy2(source, backup)
    source.write_text(updated, encoding="utf-8")
    try:
        py_compile.compile(str(source), doraise=True)
    except Exception:
        source.write_text(text, encoding="utf-8")
        raise
    return f"configured; backup: {backup}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--livetalking-dir", type=Path, default=Path("/data/LiveTalking")
    )
    args = parser.parse_args()
    rtc_source = (
        args.livetalking_dir.expanduser().resolve()
        / "server"
        / "rtc_manager.py"
    )
    app_source = args.livetalking_dir.expanduser().resolve() / "app.py"
    if not rtc_source.is_file():
        raise FileNotFoundError(f"LiveTalking RTC manager not found: {rtc_source}")
    if not app_source.is_file():
        raise FileNotFoundError(f"LiveTalking app not found: {app_source}")
    print(f"{rtc_source}: {configure(rtc_source)}")
    print(f"{app_source}: {configure_app(app_source)}")


if __name__ == "__main__":
    main()
