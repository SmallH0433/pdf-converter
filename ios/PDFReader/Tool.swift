import UIKit

/// A floating control surface that uses native Liquid Glass on iOS 26 and
/// preserves the same hierarchy with a system material on earlier releases.
final class GlassPanelView: UIVisualEffectView {
    init(cornerRadius: CGFloat = 22) {
        if #available(iOS 26.0, *) {
            super.init(effect: UIGlassEffect(style: .regular))
        } else {
            super.init(effect: UIBlurEffect(style: .systemThinMaterial))
        }
        layer.cornerRadius = cornerRadius
        layer.cornerCurve = .continuous
        clipsToBounds = true
        accessibilityContainerType = .semanticGroup
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) has not been implemented")
    }
}

enum ReaderTool: CaseIterable {
    case browse
    case pen
    case note
    case eraser
    case selectInk

    var title: String {
        switch self {
        case .browse: return "浏览"
        case .pen: return "手写"
        case .note: return "留言"
        case .eraser: return "橡皮"
        case .selectInk: return "选择笔画"
        }
    }

    var symbolName: String {
        switch self {
        case .browse: return "hand.draw"
        case .pen: return "pencil.tip"
        case .note: return "note.text.badge.plus"
        case .eraser: return "eraser"
        case .selectInk: return "selection.pin.in.out"
        }
    }
}

struct StrokeSample {
    let location: CGPoint
    let pressure: CGFloat
}

enum SelectionShape {
    case rectangle
    case lasso
}

extension UIColor {
    static let hiBrand = UIColor(red: 38 / 255, green: 96 / 255, blue: 1, alpha: 1)
    static let hiBrandContainer = UIColor { traits in
        traits.userInterfaceStyle == .dark
            ? UIColor(red: 22 / 255, green: 41 / 255, blue: 94 / 255, alpha: 1)
            : UIColor(red: 229 / 255, green: 236 / 255, blue: 1, alpha: 1)
    }
    static let hiSurface = UIColor.secondarySystemBackground
    static let hiCanvas = UIColor { traits in
        traits.userInterfaceStyle == .dark ? UIColor(white: 0.08, alpha: 1) : UIColor(white: 0.91, alpha: 1)
    }
}
