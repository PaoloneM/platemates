/**
 * Shrink a photo before upload: phone pictures are 3-12 MB, and every pixel costs the vision
 * model context tokens (it runs with an 8k context). 1280 px on the long side keeps cookbook
 * text readable at about 1,500 tokens. Re-encoding as JPEG also turns formats the backend does
 * not accept (e.g. HEIC, where the browser can decode it) into one it does.
 */
export async function downscalePhoto(file: File, maxSide = 1280, quality = 0.85): Promise<Blob> {
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.round(bitmap.width * scale)
  canvas.height = Math.round(bitmap.height * scale)
  canvas.getContext('2d')!.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  bitmap.close()
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('encoding failed'))), 'image/jpeg', quality),
  )
}
