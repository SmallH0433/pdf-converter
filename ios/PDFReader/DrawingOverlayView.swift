import PDFKit
import UIKit

@MainActor protocol DrawingOverlayViewDelegate: AnyObject {
    func overlay(_ overlay: DrawingOverlayView, didFinishStroke samples: [StrokeSample])
    func overlay(_ overlay: DrawingOverlayView, didTap location: CGPoint)
    func overlay(_ overlay: DrawingOverlayView, didErase location: CGPoint)
    func overlay(_ overlay: DrawingOverlayView, didFinishSelection points: [CGPoint], shape: SelectionShape)
}

final class DrawingOverlayView: UIView, UIGestureRecognizerDelegate {
    weak var delegate: DrawingOverlayViewDelegate?

    var tool: ReaderTool = .browse {
        didSet {
            currentPoints.removeAll()
            setNeedsDisplay()
        }
    }
    var selectionShape: SelectionShape = .rectangle
    var penColor: UIColor = .systemRed
    var selectedBounds: CGRect? {
        didSet { setNeedsDisplay() }
    }

    private var currentPoints: [StrokeSample] = []
    private var touchStart = CGPoint.zero
    private var touchMoved = false
    private weak var navigationScrollView: UIScrollView?
    private weak var navigationPDFView: PDFView?
    private var lastPanTranslation = CGPoint.zero
    private var lastPinchScale: CGFloat = 1

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        isMultipleTouchEnabled = true
        contentMode = .redraw

        let pan = UIPanGestureRecognizer(target: self, action: #selector(handleTwoFingerPan(_:)))
        pan.minimumNumberOfTouches = 2
        pan.maximumNumberOfTouches = 2
        pan.delegate = self
        addGestureRecognizer(pan)

        let pinch = UIPinchGestureRecognizer(target: self, action: #selector(handlePinch(_:)))
        pinch.delegate = self
        addGestureRecognizer(pinch)
    }

    func configureNavigation(pdfView: PDFView) {
        navigationPDFView = pdfView
        navigationScrollView = pdfView.subviews.compactMap { $0 as? UIScrollView }.first
    }

    func gestureRecognizer(
        _ gestureRecognizer: UIGestureRecognizer,
        shouldRecognizeSimultaneouslyWith otherGestureRecognizer: UIGestureRecognizer
    ) -> Bool { true }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }

    override func point(inside point: CGPoint, with event: UIEvent?) -> Bool {
        tool != .browse && super.point(inside: point, with: event)
    }

    override func touchesBegan(_ touches: Set<UITouch>, with event: UIEvent?) {
        if (event?.allTouches?.count ?? touches.count) > 1 {
            currentPoints.removeAll()
            setNeedsDisplay()
            return
        }
        guard let touch = touches.first else { return }
        touchStart = touch.location(in: self)
        touchMoved = false
        currentPoints.removeAll(keepingCapacity: true)

        switch tool {
        case .pen:
            appendSamples(from: touch, event: event)
        case .eraser:
            delegate?.overlay(self, didErase: touchStart)
        case .selectInk:
            currentPoints.append(StrokeSample(location: touchStart, pressure: 1))
        case .note, .browse:
            break
        }
        setNeedsDisplay()
    }

    override func touchesMoved(_ touches: Set<UITouch>, with event: UIEvent?) {
        guard (event?.allTouches?.count ?? touches.count) == 1 else { return }
        guard let touch = touches.first else { return }
        let location = touch.location(in: self)
        if hypot(location.x - touchStart.x, location.y - touchStart.y) > 5 {
            touchMoved = true
        }

        switch tool {
        case .pen:
            appendSamples(from: touch, event: event)
        case .eraser:
            delegate?.overlay(self, didErase: location)
        case .selectInk:
            currentPoints.append(StrokeSample(location: location, pressure: 1))
        case .note, .browse:
            break
        }
        setNeedsDisplay()
    }

    override func touchesEnded(_ touches: Set<UITouch>, with event: UIEvent?) {
        if (event?.allTouches?.count ?? touches.count) > 1 {
            currentPoints.removeAll()
            setNeedsDisplay()
            return
        }
        guard let touch = touches.first else { return }
        switch tool {
        case .pen:
            appendSamples(from: touch, event: event)
            if currentPoints.count == 1 {
                let point = currentPoints[0]
                currentPoints.append(StrokeSample(
                    location: CGPoint(x: point.location.x + 0.1, y: point.location.y + 0.1),
                    pressure: point.pressure
                ))
            }
            delegate?.overlay(self, didFinishStroke: currentPoints)
        case .note:
            if !touchMoved { delegate?.overlay(self, didTap: touch.location(in: self)) }
        case .selectInk:
            currentPoints.append(StrokeSample(location: touch.location(in: self), pressure: 1))
            delegate?.overlay(
                self,
                didFinishSelection: currentPoints.map(\.location),
                shape: selectionShape
            )
        case .eraser, .browse:
            break
        }
        currentPoints.removeAll()
        setNeedsDisplay()
    }

    override func touchesCancelled(_ touches: Set<UITouch>, with event: UIEvent?) {
        currentPoints.removeAll()
        setNeedsDisplay()
    }

    override func draw(_ rect: CGRect) {
        guard let context = UIGraphicsGetCurrentContext() else { return }
        context.setLineCap(.round)
        context.setLineJoin(.round)

        if tool == .pen, currentPoints.count > 1 {
            context.setStrokeColor(penColor.cgColor)
            context.setLineWidth(3)
            context.beginPath()
            context.move(to: currentPoints[0].location)
            for sample in currentPoints.dropFirst() { context.addLine(to: sample.location) }
            context.strokePath()
        }

        if tool == .selectInk, currentPoints.count > 1 {
            context.saveGState()
            context.setStrokeColor(UIColor.hiBrand.cgColor)
            context.setLineWidth(1.5)
            context.setLineDash(phase: 0, lengths: [7, 5])
            let points = currentPoints.map(\.location)
            if selectionShape == .rectangle, let first = points.first, let last = points.last {
                context.stroke(CGRect(
                    x: min(first.x, last.x), y: min(first.y, last.y),
                    width: abs(last.x - first.x), height: abs(last.y - first.y)
                ))
            } else {
                context.beginPath()
                context.move(to: points[0])
                for point in points.dropFirst() { context.addLine(to: point) }
                context.strokePath()
            }
            context.restoreGState()
        }

        if let selectedBounds {
            context.saveGState()
            context.setStrokeColor(UIColor.hiBrand.cgColor)
            context.setLineWidth(2)
            context.setLineDash(phase: 0, lengths: [8, 5])
            context.stroke(selectedBounds.insetBy(dx: -4, dy: -4))
            context.restoreGState()
        }
    }

    private func appendSamples(from touch: UITouch, event: UIEvent?) {
        let touches = event?.coalescedTouches(for: touch) ?? [touch]
        for item in touches {
            let pressure: CGFloat
            if item.maximumPossibleForce > 0 {
                pressure = max(0.15, min(1, item.force / item.maximumPossibleForce))
            } else {
                pressure = 0.5
            }
            currentPoints.append(StrokeSample(location: item.location(in: self), pressure: pressure))
        }
    }

    @objc private func handleTwoFingerPan(_ gesture: UIPanGestureRecognizer) {
        guard let scrollView = navigationScrollView else { return }
        if gesture.state == .began { lastPanTranslation = .zero }
        let translation = gesture.translation(in: self)
        let delta = CGPoint(
            x: translation.x - lastPanTranslation.x,
            y: translation.y - lastPanTranslation.y
        )
        lastPanTranslation = translation
        scrollView.contentOffset = CGPoint(
            x: scrollView.contentOffset.x - delta.x,
            y: scrollView.contentOffset.y - delta.y
        )
    }

    @objc private func handlePinch(_ gesture: UIPinchGestureRecognizer) {
        guard let pdfView = navigationPDFView else { return }
        if gesture.state == .began { lastPinchScale = 1 }
        let factor = gesture.scale / lastPinchScale
        lastPinchScale = gesture.scale
        pdfView.autoScales = false
        pdfView.scaleFactor = min(max(pdfView.scaleFactor * factor, pdfView.minScaleFactor), pdfView.maxScaleFactor)
    }
}
