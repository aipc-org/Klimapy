"""Model batch processing with explicit per-model success/failure reports."""

import logging
from .. import BC, SD

logger = logging.getLogger("klimapy.batch")


def process_models(jobs, *, output_dir, strict=False, bc_options=None, sd_options=None):
    """Run mappings of BC arguments; collect failures rather than silently skipping.

    Each job needs obs_path, gcm_hist_path, gcm_fut_path, model_name,
    ref_start_year, ref_end_year. Stages always run in strict mode internally.
    """
    report = {"completed": [], "failed": []}
    for index, job in enumerate(jobs):
        name = job.get("model_name", f"job_{index}")
        stage = "BC"
        correction = None
        try:
            arguments = dict(bc_options or {})
            arguments.update(job)
            arguments["strict"] = True
            correction = BC.BC(**arguments)
            stage = "SD"
            result = SD.SD(
                obs_path=job["obs_path"],
                bc_result=correction,
                output_dir=output_dir,
                ref_start_year=job["ref_start_year"],
                ref_end_year=job["ref_end_year"],
                **dict(sd_options or {}, strict=True),
            )
            report["completed"].append(dict(result, model_name=name))
        except Exception as exc:
            if strict:
                raise
            failure = {
                "model_name": name,
                "stage": stage,
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
            report["failed"].append(failure)
            logger.error("Model processing failed", extra={"failure": failure})
        finally:
            BC.close_result(correction, remove_work_files=True)
    return report
