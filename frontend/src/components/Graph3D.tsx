import { useCallback, useEffect, useMemo, useRef } from 'react'
import ForceGraph3D from '3d-force-graph'
import * as THREE from 'three'
import { useI18n } from '../i18n'
import { buildGraph3DBaseData, buildGraph3DVisibleData, type Graph3DLink as FGLink, type Graph3DNode as FGNode } from './graph3dData'
import { buildFitAllCameraTarget, buildGraph3DSceneConfig, buildGraph3DViewConfig } from './graph3dModel'
import type { GraphElement, SelectedNode } from '../state/types'

type Props = {
  elements: GraphElement[]
  selectedNodeId?: string | null
  onSelectNode: (node: SelectedNode | null) => void
  transitioning: boolean
}

type Graph3DHandle = {
  graphData: (data?: { nodes: FGNode[]; links: FGLink[] }) => { nodes: FGNode[]; links: FGLink[] } | void
  refresh: () => void
  linkVisibility: (accessor?: boolean | string | ((link: FGLink) => boolean)) => Graph3DHandle
  zoomToFit: (ms?: number, paddingPx?: number, nodeFilterFn?: (node: FGNode) => boolean) => void
  cameraPosition: (position?: { x?: number; y?: number; z?: number }, lookAt?: { x: number; y: number; z: number }, ms?: number) => void
  getGraphBbox: (nodeFilterFn?: (node: FGNode) => boolean) => { x: [number, number]; y: [number, number]; z: [number, number] } | null
  onEngineStop: (callback: (() => void) | null) => void
  controls: () =>
    | {
        enableDamping?: boolean
        dampingFactor?: number
        rotateSpeed?: number
        zoomSpeed?: number
        panSpeed?: number
        minDistance?: number
        maxDistance?: number
        autoRotate?: boolean
        autoRotateSpeed?: number
      }
    | null
  camera: () => THREE.Camera & { position: THREE.Vector3 }
  scene: () => THREE.Scene
  d3VelocityDecay: (value: number) => void
  d3Force: (name: string) => unknown
}

const LABEL_SHOW_DISTANCE = 190

function clamp(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) return min
  if (value < min) return min
  if (value > max) return max
  return value
}

function linkColor(kind: string, emphasis: FGLink['emphasis'] = 'default'): string {
  if (kind === 'contains') return 'rgba(251, 191, 36, 0.42)'
  if (kind === 'cites') return 'rgba(125, 211, 252, 0.5)'
  if (kind === 'supports') return 'rgba(74, 222, 128, 0.55)'
  if (kind === 'challenges') return 'rgba(248, 113, 113, 0.6)'
  if (kind === 'supersedes') return 'rgba(250, 204, 21, 0.56)'
  if (kind === 'similar' && emphasis === 'focus') return 'rgba(226, 232, 240, 0.82)'
  if (kind === 'similar' && emphasis === 'primary') return 'rgba(196, 211, 255, 0.58)'
  if (kind === 'similar') return 'rgba(148, 163, 184, 0.22)'
  if (kind === 'maps_to') return 'rgba(20, 184, 166, 0.56)'
  return 'rgba(148, 163, 184, 0.42)'
}

function particleColor(kind: string): string {
  if (kind === 'contains') return '#fde68a'
  if (kind === 'supports') return '#86efac'
  if (kind === 'challenges') return '#fca5a5'
  if (kind === 'supersedes') return '#fde047'
  return '#bae6fd'
}

function drawRoundedRect(
  ctx: CanvasRenderingContext2D,
  x: number,
  y: number,
  width: number,
  height: number,
  radius: number,
) {
  ctx.beginPath()
  ctx.moveTo(x + radius, y)
  ctx.lineTo(x + width - radius, y)
  ctx.quadraticCurveTo(x + width, y, x + width, y + radius)
  ctx.lineTo(x + width, y + height - radius)
  ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height)
  ctx.lineTo(x + radius, y + height)
  ctx.quadraticCurveTo(x, y + height, x, y + height - radius)
  ctx.lineTo(x, y + radius)
  ctx.quadraticCurveTo(x, y, x + radius, y)
  ctx.closePath()
}

function createLabelSprite(text: string, nodeRadius: number): THREE.Sprite {
  const compact = text.length > 34 ? `${text.slice(0, 33)}...` : text
  const logicalWidth = clamp(128 + compact.length * 6, 160, 320)
  const logicalHeight = 52
  const canvas = document.createElement('canvas')
  canvas.width = logicalWidth * 2
  canvas.height = logicalHeight * 2
  const ctx = canvas.getContext('2d')
  if (!ctx) {
    const fallback = new THREE.Sprite(new THREE.SpriteMaterial({ color: 0xffffff }))
    fallback.visible = false
    return fallback
  }
  ctx.scale(2, 2)
  ctx.clearRect(0, 0, logicalWidth, logicalHeight)

  drawRoundedRect(ctx, 1.5, 6, logicalWidth - 3, logicalHeight - 12, 10)
  ctx.fillStyle = 'rgba(4, 12, 27, 0.86)'
  ctx.fill()
  ctx.strokeStyle = 'rgba(186, 230, 253, 0.42)'
  ctx.lineWidth = 1
  ctx.stroke()

  ctx.font = '600 15px "Fira Sans", "IBM Plex Sans", sans-serif'
  ctx.fillStyle = 'rgba(240, 250, 255, 0.96)'
  ctx.textBaseline = 'middle'
  ctx.fillText(compact, 12, logicalHeight / 2 + 0.5)

  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.needsUpdate = true

  const material = new THREE.SpriteMaterial({
    map: texture,
    transparent: true,
    depthWrite: false,
    depthTest: false,
  })

  const sprite = new THREE.Sprite(material)
  sprite.scale.set(logicalWidth / 10.8, logicalHeight / 9.5, 1)
  sprite.position.set(0, nodeRadius + 7, 0)
  sprite.visible = false
  return sprite
}

function disposeSprite(sprite: THREE.Sprite) {
  const mat = sprite.material as THREE.SpriteMaterial
  mat.map?.dispose()
  mat.dispose()
}

function applyNavHint(container: HTMLDivElement | null, hint: string) {
  if (!container) return
  const navInfo = container.querySelector<HTMLDivElement>('.scene-nav-info')
  if (!navInfo) return
  navInfo.textContent = hint
}

export default function Graph3D({ elements, selectedNodeId, onSelectNode, transitioning }: Props) {
  const { t } = useI18n()
  const containerRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<Graph3DHandle | null>(null)
  const frameRef = useRef<number | null>(null)
  const autoFitTimerRef = useRef<number | null>(null)
  const pendingAutoFitRef = useRef(false)
  const viewConfigRef = useRef(buildGraph3DViewConfig(0))
  const labelSpritesRef = useRef<Map<string, THREE.Sprite>>(new Map())
  const hoveredNodeIdRef = useRef<string | null>(null)
  const onSelectNodeRef = useRef(onSelectNode)
  const selectedNodeIdRef = useRef<string | null>(selectedNodeId ?? null)
  const lastNodeSignatureRef = useRef('')

  useEffect(() => {
    onSelectNodeRef.current = onSelectNode
  }, [onSelectNode])

  useEffect(() => {
    selectedNodeIdRef.current = selectedNodeId ?? null
  }, [selectedNodeId])

  const baseData = useMemo(() => buildGraph3DBaseData(elements), [elements])
  const { nodes, links, nodeSignature } = useMemo(() => buildGraph3DVisibleData(baseData, null), [baseData])
  const initialNodeCountRef = useRef(baseData.nodes.length)

  const applyGraphFit = useCallback((fg: Graph3DHandle, animateMs: number) => {
    const container = containerRef.current
    const graphData = fg.graphData() as { nodes: FGNode[]; links: FGLink[] } | void
    const nodeCount = graphData?.nodes.length ?? nodes.length
    const finiteNodeFilter = (node: FGNode) => Number.isFinite(node.x) && Number.isFinite(node.y) && Number.isFinite(node.z)
    const camera = fg.camera() as THREE.Camera & {
      position: THREE.Vector3
      fov?: number
      aspect?: number
      far?: number
      updateProjectionMatrix?: () => void
    }
    const bounds = fg.getGraphBbox?.(finiteNodeFilter)
    if (!container || !bounds) {
      fg.zoomToFit(animateMs, viewConfigRef.current.autoFitPadding)
      return
    }

    const aspect = Math.max(container.clientWidth, 1) / Math.max(container.clientHeight, 1)
    const fitTarget = buildFitAllCameraTarget(bounds, {
      aspect,
      fovDeg: camera instanceof THREE.PerspectiveCamera ? camera.fov : Number(camera.fov) || 40,
      minDistance: viewConfigRef.current.minDistance,
    })
    if (![fitTarget.position.x, fitTarget.position.y, fitTarget.position.z, fitTarget.lookAt.x, fitTarget.lookAt.y, fitTarget.lookAt.z].every(Number.isFinite)) {
      fg.zoomToFit(animateMs, viewConfigRef.current.autoFitPadding, finiteNodeFilter)
      return
    }
    viewConfigRef.current = buildGraph3DViewConfig(nodeCount, fitTarget.diagonal)
    const sceneConfig = buildGraph3DSceneConfig(nodeCount, fitTarget.diagonal, fitTarget.distance)

    const controls = fg.controls()
    if (controls) {
      controls.zoomSpeed = viewConfigRef.current.zoomSpeed
      controls.minDistance = viewConfigRef.current.minDistance
      controls.maxDistance = Math.max(viewConfigRef.current.maxDistance, Math.round(fitTarget.distance * 8))
    }

    if (camera instanceof THREE.PerspectiveCamera) {
      camera.aspect = aspect
      camera.far = Math.max(camera.far, fitTarget.distance * 10)
      camera.updateProjectionMatrix()
    } else if (typeof camera.updateProjectionMatrix === 'function' && typeof camera.far === 'number') {
      camera.far = Math.max(camera.far, fitTarget.distance * 10)
        camera.updateProjectionMatrix()
    }

    fg.scene().fog = new THREE.FogExp2(0x01030a, sceneConfig.fogDensity)
    fg.cameraPosition(fitTarget.position, fitTarget.lookAt, animateMs)
  }, [nodes.length])

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const labelSprites = labelSpritesRef.current
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    viewConfigRef.current = buildGraph3DViewConfig(initialNodeCountRef.current)
    const fg = (() => {
      const originalWarn = console.warn
      const suppressClockWarning = (message: unknown) =>
        typeof message === 'string' && message.includes('THREE.THREE.Clock: This module has been deprecated')
      console.warn = (...args: unknown[]) => {
        if (suppressClockWarning(args[0])) return
        originalWarn(...args)
      }
      try {
        return new ForceGraph3D(container, { controlType: 'orbit' })
      } finally {
        console.warn = originalWarn
      }
    })()

    fg
      .backgroundColor('#01030a')
      .nodeLabel((n) => (n as FGNode).label)
      .nodeColor((n) => (n as FGNode).color)
      .nodeVal((n) => (n as FGNode).val)
      .nodeThreeObject((n) => {
        const node = n as FGNode
        const imported = node.kind === 'paper' ? node.ingested !== false : true
        const radius = Math.max(3.4, node.val)
        const color = new THREE.Color(node.color)
        const group = new THREE.Group()

        const sphere = new THREE.Mesh(
          new THREE.SphereGeometry(radius, 18, 18),
          new THREE.MeshStandardMaterial({
            color,
            emissive: color.clone().multiplyScalar(0.28),
            emissiveIntensity: 1.08,
            roughness: 0.32,
            metalness: 0.12,
            transparent: true,
            opacity: imported ? 0.96 : 0.56,
          }),
        )
        group.add(sphere)

        const aura = new THREE.Mesh(
          new THREE.SphereGeometry(radius * 1.8, 16, 16),
          new THREE.MeshBasicMaterial({
            color: new THREE.Color(node.auraColor ?? node.color),
            transparent: true,
            opacity: node.kind === 'community' ? (imported ? 0.12 : 0.05) : imported ? 0.08 : 0.03,
            side: THREE.BackSide,
          }),
        )
        group.add(aura)

        const ring = new THREE.Mesh(
          new THREE.TorusGeometry(radius * 1.24, Math.max(0.24, radius * 0.08), 10, 40),
          new THREE.MeshBasicMaterial({
            color: new THREE.Color(node.ringColor ?? node.color).lerp(new THREE.Color('#f8fafc'), node.kind === 'community' ? 0.16 : 0.4),
            transparent: true,
            opacity: node.kind === 'community' ? (imported ? 0.58 : 0.28) : imported ? 0.42 : 0.22,
          }),
        )
        ring.rotation.x = Math.PI / 2.3
        group.add(ring)

        const labelSprite = createLabelSprite(node.label, radius)
        labelSprites.set(node.id, labelSprite)
        group.add(labelSprite)

        return group
      })
      .nodeThreeObjectExtend(false)
      .linkVisibility((link) => (link as FGLink).visible !== false)
      .linkWidth((link) => {
        const edge = link as FGLink
        if (edge.visible === false) return 0
        if (edge.kind === 'similar') {
          if (edge.emphasis === 'focus') return 1.2 + edge.weight * 1.4
          if (edge.emphasis === 'primary') return 0.72 + edge.weight * 1.05
          return 0.24 + edge.weight * 0.55
        }
        return 0.8 + edge.weight * 1.5
      })
      .linkColor((link) => (link as FGLink).displayColor ?? linkColor((link as FGLink).kind, (link as FGLink).emphasis))
      .linkOpacity(0.78)
      .linkDirectionalParticles((link) => {
        const edge = link as FGLink
        if (edge.visible === false) return 0
        if (edge.kind === 'similar') {
          if (edge.emphasis === 'focus') return 2
          if (edge.emphasis === 'primary') return 1
          return 0
        }
        return edge.kind === 'supports' || edge.kind === 'challenges' ? 2 : 1
      })
      .linkDirectionalParticleWidth((link) => {
        const edge = link as FGLink
        if (edge.visible === false) return 0
        if (edge.kind === 'similar') {
          if (edge.emphasis === 'focus') return 1.9
          if (edge.emphasis === 'primary') return 1.45
          return 0
        }
        return edge.kind === 'supports' ? 2.6 : 2
      })
      .linkDirectionalParticleColor((link) => particleColor((link as FGLink).kind))
      .onNodeClick((n) => {
        const node = n as FGNode
        if (selectedNodeIdRef.current === node.id) return
        selectedNodeIdRef.current = node.id
        onSelectNodeRef.current({
          id: node.id,
          kind: node.kind,
          label: node.label,
          description: node.description,
          communityId: node.communityId,
          clusterKey: node.clusterKey,
          paperId: node.paperId,
          paperSource: node.paperSource,
          paperTitle: node.paperTitle,
          stepType: node.stepType,
          textbookId: node.textbookId,
          chapterId: node.chapterId,
        })
      })
      .onNodeHover((n) => {
        hoveredNodeIdRef.current = n ? (n as FGNode).id : null
        container.style.cursor = n ? 'pointer' : 'default'
      })
      .onBackgroundClick(() => {
        if (!selectedNodeIdRef.current) return
        selectedNodeIdRef.current = null
        onSelectNodeRef.current(null)
      })

    const controls = fg.controls() as
      | {
          enableDamping?: boolean
          dampingFactor?: number
          rotateSpeed?: number
          zoomSpeed?: number
          panSpeed?: number
          minDistance?: number
          maxDistance?: number
          autoRotate?: boolean
          autoRotateSpeed?: number
        }
      | null
    if (controls) {
      controls.enableDamping = true
      controls.dampingFactor = 0.08
      controls.rotateSpeed = 0.7
      controls.zoomSpeed = viewConfigRef.current.zoomSpeed
      controls.panSpeed = 0.8
      controls.minDistance = viewConfigRef.current.minDistance
      controls.maxDistance = viewConfigRef.current.maxDistance
      controls.autoRotate = false
      controls.autoRotateSpeed = prefersReducedMotion ? 0 : 0.2
    }

    fg.d3VelocityDecay(0.32)
    const chargeForce = fg.d3Force('charge') as { strength?: (value: number) => void } | undefined
    chargeForce?.strength?.(-120)
    const linkForce = fg.d3Force('link') as { distance?: (fn: (l: FGLink) => number) => void; strength?: (v: number) => void } | undefined
    linkForce?.distance?.((l) => {
      if (l.kind === 'contains') return 58 + (1 - l.weight) * 28
      if (l.kind === 'relates_to') return 82 + (1 - l.weight) * 32
      if (l.kind === 'maps_to') return 108 + (1 - l.weight) * 36
      if (l.kind === 'cites') return 150 + (1 - l.weight) * 60
      return 95 + (1 - l.weight) * 50
    })
    linkForce?.strength?.(0.22)

    const scene = fg.scene()
    scene.fog = null
    scene.add(new THREE.AmbientLight(0x94a3b8, 1.5))
    scene.add(new THREE.HemisphereLight(0x7dd3fc, 0x020617, 1.3))
    const keyLight = new THREE.DirectionalLight(0xffffff, 1.55)
    keyLight.position.set(90, 120, 120)
    scene.add(keyLight)
    const rimLight = new THREE.PointLight(0x7dd3fc, 1.25, 420)
    rimLight.position.set(-120, -70, -130)
    scene.add(rimLight)

    const starGeometry = new THREE.BufferGeometry()
    const starPoints = new Float32Array(1200 * 3)
    for (let i = 0; i < 1200; i += 1) {
      starPoints[i * 3] = (Math.random() - 0.5) * 1800
      starPoints[i * 3 + 1] = (Math.random() - 0.5) * 1800
      starPoints[i * 3 + 2] = (Math.random() - 0.5) * 1800
    }
    starGeometry.setAttribute('position', new THREE.BufferAttribute(starPoints, 3))
    const starMaterial = new THREE.PointsMaterial({
      color: 0x9cc7ff,
      size: 1.3,
      transparent: true,
      opacity: 0.26,
      depthWrite: false,
    })
    const stars = new THREE.Points(starGeometry, starMaterial)
    scene.add(stars)

    const scratch = new THREE.Vector3()
    const updateLabels = () => {
      const camera = fg.camera()
      const cameraPosition = camera.position
      const graphData = fg.graphData() as unknown as { nodes: FGNode[] }
      const hoveredId = hoveredNodeIdRef.current

      for (const node of graphData.nodes) {
        const sprite = labelSprites.get(node.id)
        if (!sprite) continue
        const dist = cameraPosition.distanceTo(scratch.set(node.x ?? 0, node.y ?? 0, node.z ?? 0))
        sprite.visible = dist < LABEL_SHOW_DISTANCE || hoveredId === node.id
      }
      frameRef.current = window.requestAnimationFrame(updateLabels)
    }

    fg.onEngineStop(() => {
      if (!pendingAutoFitRef.current || !graphRef.current) return
      applyGraphFit(graphRef.current, viewConfigRef.current.autoFitMs)
      pendingAutoFitRef.current = false
    })

    frameRef.current = window.requestAnimationFrame(updateLabels)
    graphRef.current = fg as unknown as Graph3DHandle
    applyNavHint(container, t('左键旋转，滚轮/中键缩放，右键平移', 'Left-click: rotate, mouse wheel/middle-click: zoom, right-click: pan'))

    return () => {
      if (frameRef.current) window.cancelAnimationFrame(frameRef.current)
      frameRef.current = null
      if (autoFitTimerRef.current) window.clearTimeout(autoFitTimerRef.current)
      autoFitTimerRef.current = null
      pendingAutoFitRef.current = false
      hoveredNodeIdRef.current = null
      container.style.cursor = 'default'

      starGeometry.dispose()
      starMaterial.dispose()
      scene.remove(stars)

      for (const sprite of labelSprites.values()) {
        disposeSprite(sprite)
      }
      labelSprites.clear()

      try {
        ;(fg as { _destructor?: () => void })._destructor?.()
      } catch {
        // no-op
      }
      graphRef.current = null
    }
  }, [applyGraphFit, t])

  useEffect(() => {
    applyNavHint(
      containerRef.current,
      t('左键旋转，滚轮/中键缩放，右键平移', 'Left-click: rotate, mouse wheel/middle-click: zoom, right-click: pan'),
    )
  }, [t])

  useEffect(() => {
    const fg = graphRef.current
    if (!fg) return
    viewConfigRef.current = buildGraph3DViewConfig(nodes.length)
    const controls = fg.controls()
    if (controls) {
      controls.zoomSpeed = viewConfigRef.current.zoomSpeed
      controls.minDistance = viewConfigRef.current.minDistance
      controls.maxDistance = viewConfigRef.current.maxDistance
    }
    const shouldAutoFit = nodes.length > 0 && lastNodeSignatureRef.current !== nodeSignature
    pendingAutoFitRef.current = shouldAutoFit
    lastNodeSignatureRef.current = nodeSignature
    fg.graphData({ nodes, links })
    if (autoFitTimerRef.current) window.clearTimeout(autoFitTimerRef.current)
    if (pendingAutoFitRef.current) {
      autoFitTimerRef.current = window.setTimeout(() => {
        autoFitTimerRef.current = null
        if (!graphRef.current) return
        applyGraphFit(graphRef.current, viewConfigRef.current.autoFitMs)
      }, 720)
    }
  }, [applyGraphFit, links, nodeSignature, nodes])

  useEffect(() => {
    const fg = graphRef.current
    if (!fg) return

    const nextVisible = buildGraph3DVisibleData(baseData, selectedNodeId ?? null)
    const current = fg.graphData() as { nodes: FGNode[]; links: FGLink[] } | void
    const currentLinks = current?.links ?? []
    if (!currentLinks.length) return

    const nextLinksById = new Map(nextVisible.links.map((link) => [link.id, link]))
    let changed = false
    for (const link of currentLinks) {
      const next = nextLinksById.get(link.id)
      if (!next) continue
      if (link.visible !== next.visible) {
        link.visible = next.visible
        changed = true
      }
      if (link.emphasis !== next.emphasis) {
        link.emphasis = next.emphasis
        changed = true
      }
      if (link.displayColor !== next.displayColor) {
        link.displayColor = next.displayColor
        changed = true
      }
    }

    selectedNodeIdRef.current = selectedNodeId ?? null
    if (changed) fg.refresh()
  }, [baseData, selectedNodeId])

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '100%',
        opacity: transitioning ? 0.5 : 1,
        transition: 'opacity 220ms ease',
      }}
    />
  )
}
