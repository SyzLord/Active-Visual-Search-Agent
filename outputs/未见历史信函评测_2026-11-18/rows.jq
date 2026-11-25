["case","collection","policy","date_pass","date_iou","text_pass","text_iou","joint_pass","ocr_pixels","preview_pixels","total_pixels","date_in_stamp_stage","line_rereads"],
(.rows[] | [
  .case,.collection,.policy,.fields[0].strict,.fields[0].iou,.fields[1].strict,.fields[1].iou,
  .strict,.trace.spent,.trace.preview_pixels,.trace.total_pixels,((.trace.date_pages|length)>0),
  ([.trace.steps[]|select(.view|startswith("article-confirm:"))]|length)
])
| @tsv
