import PDFKit
import UIKit
import UniformTypeIdentifiers

@MainActor
final class ReaderViewController: UIViewController {
    private let pdfView = PDFView()
    private let overlay = DrawingOverlayView()
    private let titleLabel = UILabel()
    private let statusLabel = UILabel()
    private let pageLabel = UILabel()
    private let searchBar = GlassPanelView()
    private let searchField = UITextField()
    private let searchCountLabel = UILabel()
    private let selectionBar = GlassPanelView()
    private let selectionCountLabel = UILabel()
    private let actionUndoManager = UndoManager()
    private lazy var topBarPanel = makeTopBar()
    private let toolBarPanel = GlassPanelView()
    private let toolScrollView = UIScrollView()
    private let toolStack = UIStackView()
    private let contextStack = UIStackView()
    private lazy var bottomBarPanel = makeBottomBar()
    private var adaptiveChromeConstraints: [NSLayoutConstraint] = []
    private var isUsingPadLandscapeLayout: Bool?

    private var documentURL: URL?
    private var securityScopedURL: URL?
    private var isDirty = false
    private var currentTool: ReaderTool = .pen
    private var toolButtons: [ReaderTool: UIButton] = [:]
    private var searchHits: [PDFSelection] = []
    private var currentSearchHit = -1
    private var selectedInk: [PDFAnnotation] = []
    private var selectionShape: SelectionShape = .rectangle

    private let penColors: [(UIColor, String)] = [
        (.systemRed, "红"), (.label, "黑"), (.systemBlue, "蓝"), (.systemGreen, "绿")
    ]
    private var penColorIndex = 0
    private var selectionColorIndex = 0
    private lazy var penColorButton = iconButton(
        symbol: "paintpalette", label: "笔色：红", kind: .chip, action: #selector(cyclePenColor)
    )
    private lazy var selectionColorButton = iconButton(
        symbol: "paintpalette", label: "所选笔画颜色：红", kind: .chip,
        action: #selector(cycleSelectionColor)
    )
    private lazy var selectionShapeButton = iconButton(
        symbol: "rectangle.dashed", label: "选择模式：矩形", kind: .chip,
        action: #selector(toggleSelectionShape)
    )

    private enum ButtonKind { case primary, tonal, ghost, chip }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemBackground
        buildInterface()
        observePDFView()
        setTool(.pen)
        updatePenColorButton()
        updateSelectionColorButton()

        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleIncomingPDF(_:)),
            name: .openPDFURL,
            object: nil
        )
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        overlay.configureNavigation(pdfView: pdfView)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        updateAdaptiveChromeLayout()
    }

    deinit {
        securityScopedURL?.stopAccessingSecurityScopedResource()
        NotificationCenter.default.removeObserver(self)
    }

    private func buildInterface() {
        let pdfContainer = UIView()
        pdfContainer.backgroundColor = .hiCanvas
        pdfContainer.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(pdfContainer)

        pdfView.translatesAutoresizingMaskIntoConstraints = false
        pdfView.backgroundColor = .hiCanvas
        pdfView.displayMode = .singlePage
        pdfView.displayDirection = .vertical
        pdfView.autoScales = true
        pdfView.usePageViewController(true, withViewOptions: nil)
        pdfContainer.addSubview(pdfView)

        overlay.translatesAutoresizingMaskIntoConstraints = false
        overlay.delegate = self
        pdfContainer.addSubview(overlay)

        NSLayoutConstraint.activate([
            pdfContainer.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            pdfContainer.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            pdfContainer.topAnchor.constraint(equalTo: view.topAnchor),
            pdfContainer.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            pdfView.leadingAnchor.constraint(equalTo: pdfContainer.leadingAnchor),
            pdfView.trailingAnchor.constraint(equalTo: pdfContainer.trailingAnchor),
            pdfView.topAnchor.constraint(equalTo: pdfContainer.topAnchor),
            pdfView.bottomAnchor.constraint(equalTo: pdfContainer.bottomAnchor),
            overlay.leadingAnchor.constraint(equalTo: pdfContainer.leadingAnchor),
            overlay.trailingAnchor.constraint(equalTo: pdfContainer.trailingAnchor),
            overlay.topAnchor.constraint(equalTo: pdfContainer.topAnchor),
            overlay.bottomAnchor.constraint(equalTo: pdfContainer.bottomAnchor),
        ])

        configureToolBar()
        configureSearchBar()
        configureSelectionBar()

        contextStack.axis = .vertical
        contextStack.spacing = 8
        contextStack.translatesAutoresizingMaskIntoConstraints = false
        contextStack.addArrangedSubview(searchBar)
        contextStack.addArrangedSubview(selectionBar)

        topBarPanel.translatesAutoresizingMaskIntoConstraints = false
        toolBarPanel.translatesAutoresizingMaskIntoConstraints = false
        bottomBarPanel.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(topBarPanel)
        view.addSubview(toolBarPanel)
        view.addSubview(contextStack)
        view.addSubview(bottomBarPanel)

        NSLayoutConstraint.activate([
            topBarPanel.leadingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 10),
            topBarPanel.trailingAnchor.constraint(equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -10),
            topBarPanel.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor, constant: 8),
            topBarPanel.heightAnchor.constraint(equalToConstant: 52),
            bottomBarPanel.leadingAnchor.constraint(
                greaterThanOrEqualTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 10
            ),
            bottomBarPanel.trailingAnchor.constraint(
                equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -10
            ),
            bottomBarPanel.bottomAnchor.constraint(
                equalTo: view.safeAreaLayoutGuide.bottomAnchor, constant: -8
            ),
            bottomBarPanel.heightAnchor.constraint(equalToConstant: 52),
        ])
        updateAdaptiveChromeLayout(force: true)
    }

    private func makeTopBar() -> UIView {
        let stack = UIStackView()
        stack.axis = .horizontal
        stack.alignment = .center
        stack.spacing = 4
        stack.layoutMargins = UIEdgeInsets(top: 6, left: 8, bottom: 6, right: 8)
        stack.isLayoutMarginsRelativeArrangement = true

        stack.addArrangedSubview(iconButton(
            symbol: "house", label: "返回主页", kind: .ghost, action: #selector(returnHome)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "folder", label: "打开 PDF", kind: .primary, action: #selector(openPDF)
        ))

        titleLabel.text = "PDF 阅读器"
        titleLabel.font = .systemFont(ofSize: 17, weight: .semibold)
        titleLabel.lineBreakMode = .byTruncatingMiddle
        titleLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        stack.addArrangedSubview(titleLabel)

        stack.addArrangedSubview(iconButton(
            symbol: "magnifyingglass", label: "查找", kind: .ghost, action: #selector(toggleSearch)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "square.and.arrow.down", label: "保存", kind: .ghost, action: #selector(savePDF)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "doc.badge.plus", label: "另存为", kind: .ghost, action: #selector(exportPDF)
        ))
        return glassPanel(containing: stack)
    }

    private func configureToolBar() {
        toolScrollView.showsHorizontalScrollIndicator = false
        toolScrollView.showsVerticalScrollIndicator = false
        toolScrollView.translatesAutoresizingMaskIntoConstraints = false
        toolBarPanel.contentView.addSubview(toolScrollView)

        toolStack.axis = .horizontal
        toolStack.spacing = 4
        toolStack.layoutMargins = UIEdgeInsets(top: 2, left: 8, bottom: 8, right: 8)
        toolStack.isLayoutMarginsRelativeArrangement = true
        toolStack.translatesAutoresizingMaskIntoConstraints = false
        toolScrollView.addSubview(toolStack)

        NSLayoutConstraint.activate([
            toolScrollView.leadingAnchor.constraint(equalTo: toolBarPanel.contentView.leadingAnchor),
            toolScrollView.trailingAnchor.constraint(equalTo: toolBarPanel.contentView.trailingAnchor),
            toolScrollView.topAnchor.constraint(equalTo: toolBarPanel.contentView.topAnchor),
            toolScrollView.bottomAnchor.constraint(equalTo: toolBarPanel.contentView.bottomAnchor),
            toolStack.leadingAnchor.constraint(equalTo: toolScrollView.contentLayoutGuide.leadingAnchor),
            toolStack.trailingAnchor.constraint(equalTo: toolScrollView.contentLayoutGuide.trailingAnchor),
            toolStack.topAnchor.constraint(equalTo: toolScrollView.contentLayoutGuide.topAnchor),
            toolStack.bottomAnchor.constraint(equalTo: toolScrollView.contentLayoutGuide.bottomAnchor),
        ])

        for tool in ReaderTool.allCases {
            let button = iconButton(
                symbol: tool.symbolName,
                label: tool.title,
                kind: .chip,
                action: #selector(toolTapped(_:))
            )
            button.tag = ReaderTool.allCases.firstIndex(of: tool) ?? 0
            toolButtons[tool] = button
            toolStack.addArrangedSubview(button)
        }
        toolStack.addArrangedSubview(selectionShapeButton)
        toolStack.addArrangedSubview(penColorButton)
        toolStack.addArrangedSubview(iconButton(
            symbol: "arrow.uturn.backward", label: "撤销", kind: .chip, action: #selector(undoAction)
        ))
    }

    private func updateAdaptiveChromeLayout(force: Bool = false) {
        let usePadLandscape = UIDevice.current.userInterfaceIdiom == .pad
            && view.bounds.width > view.bounds.height
            && view.bounds.width >= 900
        guard force || isUsingPadLandscapeLayout != usePadLandscape else { return }
        isUsingPadLandscapeLayout = usePadLandscape

        NSLayoutConstraint.deactivate(adaptiveChromeConstraints)
        if usePadLandscape {
            toolStack.axis = .vertical
            toolStack.alignment = .center
            toolStack.layoutMargins = UIEdgeInsets(top: 8, left: 8, bottom: 8, right: 8)
            toolScrollView.alwaysBounceHorizontal = false
            toolScrollView.alwaysBounceVertical = true
            adaptiveChromeConstraints = [
                toolStack.widthAnchor.constraint(equalTo: toolScrollView.frameLayoutGuide.widthAnchor),
                toolBarPanel.leadingAnchor.constraint(
                    equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 12
                ),
                toolBarPanel.topAnchor.constraint(equalTo: topBarPanel.bottomAnchor, constant: 12),
                toolBarPanel.widthAnchor.constraint(equalToConstant: 56),
                toolBarPanel.heightAnchor.constraint(equalToConstant: 364),
                toolBarPanel.bottomAnchor.constraint(
                    lessThanOrEqualTo: bottomBarPanel.topAnchor, constant: -12
                ),
                contextStack.leadingAnchor.constraint(equalTo: toolBarPanel.trailingAnchor, constant: 12),
                contextStack.trailingAnchor.constraint(
                    equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -10
                ),
                contextStack.topAnchor.constraint(equalTo: topBarPanel.bottomAnchor, constant: 12),
                contextStack.bottomAnchor.constraint(
                    lessThanOrEqualTo: bottomBarPanel.topAnchor, constant: -12
                ),
            ]
        } else {
            toolStack.axis = .horizontal
            toolStack.alignment = .fill
            toolStack.layoutMargins = UIEdgeInsets(top: 2, left: 8, bottom: 8, right: 8)
            toolScrollView.alwaysBounceHorizontal = true
            toolScrollView.alwaysBounceVertical = false
            adaptiveChromeConstraints = [
                toolStack.heightAnchor.constraint(equalTo: toolScrollView.frameLayoutGuide.heightAnchor),
                toolBarPanel.leadingAnchor.constraint(
                    equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 10
                ),
                toolBarPanel.trailingAnchor.constraint(
                    equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -10
                ),
                toolBarPanel.topAnchor.constraint(equalTo: topBarPanel.bottomAnchor, constant: 8),
                toolBarPanel.heightAnchor.constraint(equalToConstant: 50),
                contextStack.leadingAnchor.constraint(
                    equalTo: view.safeAreaLayoutGuide.leadingAnchor, constant: 10
                ),
                contextStack.trailingAnchor.constraint(
                    equalTo: view.safeAreaLayoutGuide.trailingAnchor, constant: -10
                ),
                contextStack.topAnchor.constraint(equalTo: toolBarPanel.bottomAnchor, constant: 8),
                contextStack.bottomAnchor.constraint(
                    lessThanOrEqualTo: bottomBarPanel.topAnchor, constant: -8
                ),
            ]
        }
        NSLayoutConstraint.activate(adaptiveChromeConstraints)
    }

    private func configureSearchBar() {
        searchBar.isHidden = true
        searchBar.translatesAutoresizingMaskIntoConstraints = false
        searchBar.heightAnchor.constraint(equalToConstant: 52).isActive = true

        let stack = UIStackView()
        stack.axis = .horizontal
        stack.alignment = .center
        stack.spacing = 4
        stack.translatesAutoresizingMaskIntoConstraints = false
        searchBar.contentView.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: searchBar.contentView.leadingAnchor, constant: 12),
            stack.trailingAnchor.constraint(equalTo: searchBar.contentView.trailingAnchor, constant: -8),
            stack.topAnchor.constraint(equalTo: searchBar.contentView.topAnchor, constant: 6),
            stack.bottomAnchor.constraint(equalTo: searchBar.contentView.bottomAnchor, constant: -6),
        ])

        searchField.placeholder = "输入查找内容（文字层）"
        searchField.borderStyle = .roundedRect
        searchField.clearButtonMode = .whileEditing
        searchField.returnKeyType = .search
        searchField.delegate = self
        searchField.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        stack.addArrangedSubview(searchField)
        stack.addArrangedSubview(iconButton(
            symbol: "magnifyingglass", label: "开始查找", kind: .tonal, action: #selector(startSearch)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "arrow.up", label: "上一个结果", kind: .tonal, action: #selector(previousSearchHit)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "arrow.down", label: "下一个结果", kind: .tonal, action: #selector(nextSearchHit)
        ))
        searchCountLabel.font = .systemFont(ofSize: 12)
        searchCountLabel.textColor = .secondaryLabel
        stack.addArrangedSubview(searchCountLabel)
    }

    private func configureSelectionBar() {
        selectionBar.isHidden = true
        selectionBar.translatesAutoresizingMaskIntoConstraints = false
        selectionBar.heightAnchor.constraint(equalToConstant: 52).isActive = true

        let scroll = UIScrollView()
        scroll.showsHorizontalScrollIndicator = false
        scroll.translatesAutoresizingMaskIntoConstraints = false
        selectionBar.contentView.addSubview(scroll)
        NSLayoutConstraint.activate([
            scroll.leadingAnchor.constraint(equalTo: selectionBar.contentView.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: selectionBar.contentView.trailingAnchor),
            scroll.topAnchor.constraint(equalTo: selectionBar.contentView.topAnchor),
            scroll.bottomAnchor.constraint(equalTo: selectionBar.contentView.bottomAnchor),
        ])

        let stack = UIStackView()
        stack.axis = .horizontal
        stack.alignment = .center
        stack.spacing = 4
        stack.layoutMargins = UIEdgeInsets(top: 6, left: 8, bottom: 6, right: 8)
        stack.isLayoutMarginsRelativeArrangement = true
        stack.translatesAutoresizingMaskIntoConstraints = false
        scroll.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor),
            stack.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor),
            stack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor),
            stack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor),
            stack.heightAnchor.constraint(equalTo: scroll.frameLayoutGuide.heightAnchor),
        ])

        selectionCountLabel.font = .systemFont(ofSize: 13)
        selectionCountLabel.textColor = .secondaryLabel
        stack.addArrangedSubview(selectionCountLabel)
        stack.addArrangedSubview(selectionColorButton)
        stack.addArrangedSubview(iconButton(
            symbol: "plus.magnifyingglass", label: "放大所选笔画", kind: .chip,
            action: #selector(scaleSelectionUp)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "minus.magnifyingglass", label: "缩小所选笔画", kind: .chip,
            action: #selector(scaleSelectionDown)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "rotate.left", label: "向左旋转", kind: .chip, action: #selector(rotateSelectionLeft)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "rotate.right", label: "向右旋转", kind: .chip, action: #selector(rotateSelectionRight)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "trash", label: "删除所选笔画", kind: .chip, action: #selector(deleteSelection)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "checkmark", label: "完成选择", kind: .chip, action: #selector(clearSelection)
        ))
    }

    private func makeBottomBar() -> UIView {
        let stack = UIStackView()
        stack.axis = .horizontal
        stack.alignment = .center
        stack.spacing = 4
        stack.layoutMargins = UIEdgeInsets(top: 6, left: 8, bottom: 6, right: 8)
        stack.isLayoutMarginsRelativeArrangement = true

        statusLabel.text = "打开或选择 PDF 开始阅读"
        statusLabel.font = .systemFont(ofSize: 12)
        statusLabel.textColor = .tertiaryLabel
        statusLabel.lineBreakMode = .byTruncatingTail
        statusLabel.setContentCompressionResistancePriority(.defaultLow, for: .horizontal)
        stack.addArrangedSubview(statusLabel)

        stack.addArrangedSubview(iconButton(
            symbol: "chevron.left", label: "上一页", kind: .tonal, action: #selector(previousPage)
        ))
        pageLabel.text = "0 / 0"
        pageLabel.font = .monospacedDigitSystemFont(ofSize: 13, weight: .regular)
        pageLabel.textAlignment = .center
        stack.addArrangedSubview(pageLabel)
        stack.addArrangedSubview(iconButton(
            symbol: "chevron.right", label: "下一页", kind: .tonal, action: #selector(nextPage)
        ))
        stack.addArrangedSubview(iconButton(
            symbol: "arrow.left.and.right", label: "适应宽度", kind: .ghost, action: #selector(fitToWidth)
        ))
        return glassPanel(containing: stack)
    }

    private func glassPanel(containing content: UIView) -> GlassPanelView {
        let panel = GlassPanelView()
        content.translatesAutoresizingMaskIntoConstraints = false
        panel.contentView.addSubview(content)
        NSLayoutConstraint.activate([
            content.leadingAnchor.constraint(equalTo: panel.contentView.leadingAnchor),
            content.trailingAnchor.constraint(equalTo: panel.contentView.trailingAnchor),
            content.topAnchor.constraint(equalTo: panel.contentView.topAnchor),
            content.bottomAnchor.constraint(equalTo: panel.contentView.bottomAnchor),
        ])
        return panel
    }

    private func iconButton(
        symbol: String,
        label: String,
        kind: ButtonKind,
        action: Selector
    ) -> UIButton {
        var configuration: UIButton.Configuration
        if #available(iOS 26.0, *) {
            // The enclosing panel owns the glass material; keep controls on a
            // single glass layer instead of nesting glass inside glass.
            configuration = .plain()
            configuration.baseForegroundColor = kind == .primary ? .hiBrand : .label
        } else {
            switch kind {
            case .primary:
                configuration = .filled()
                configuration.baseBackgroundColor = .hiBrand
                configuration.baseForegroundColor = .white
            case .tonal:
                configuration = .gray()
                configuration.baseForegroundColor = .label
            case .ghost:
                configuration = .plain()
                configuration.baseForegroundColor = .hiBrand
            case .chip:
                configuration = .gray()
                configuration.baseForegroundColor = .secondaryLabel
            }
        }
        configuration.image = UIImage(systemName: symbol)
        configuration.cornerStyle = .medium
        configuration.contentInsets = NSDirectionalEdgeInsets(top: 8, leading: 8, bottom: 8, trailing: 8)

        let button = UIButton(configuration: configuration)
        button.accessibilityLabel = label
        button.isPointerInteractionEnabled = true
        button.addTarget(self, action: action, for: .touchUpInside)
        button.widthAnchor.constraint(equalToConstant: 40).isActive = true
        button.heightAnchor.constraint(equalToConstant: 40).isActive = true
        return button
    }

    private func observePDFView() {
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(pageChanged),
            name: .PDFViewPageChanged,
            object: pdfView
        )
    }

    @objc private func openPDF() {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.pdf], asCopy: false)
        picker.delegate = self
        present(picker, animated: true)
    }

    func openDocument(at url: URL) {
        guard isDirty else {
            loadDocument(at: url)
            return
        }

        let alert = UIAlertController(
            title: "未保存的修改",
            message: "打开其他 PDF 前是否保存当前文件？",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "取消", style: .cancel))
        alert.addAction(UIAlertAction(title: "放弃修改", style: .destructive) { [weak self] _ in
            self?.loadDocument(at: url)
        })
        alert.addAction(UIAlertAction(title: "保存并打开", style: .default) { [weak self] _ in
            guard let self,
                  let document = self.pdfView.document,
                  let currentURL = self.documentURL else { return }
            if document.write(to: currentURL) {
                self.isDirty = false
                self.loadDocument(at: url)
            } else {
                self.showError("无法写入原文件，请先使用“另存为”。")
            }
        })
        present(alert, animated: true)
    }

    private func loadDocument(at url: URL) {
        let hasSecurityScope = url.startAccessingSecurityScopedResource()

        guard let document = PDFDocument(url: url) else {
            showError("无法打开这个 PDF。")
            if hasSecurityScope { url.stopAccessingSecurityScopedResource() }
            return
        }
        securityScopedURL?.stopAccessingSecurityScopedResource()
        securityScopedURL = hasSecurityScope ? url : nil
        documentURL = url
        pdfView.document = document
        pdfView.autoScales = true
        titleLabel.text = url.deletingPathExtension().lastPathComponent
        isDirty = false
        statusLabel.text = "已保存"
        actionUndoManager.removeAllActions()
        clearSelection()
        clearSearch()
        updatePageLabel()
    }

    @objc private func savePDF() {
        guard let document = pdfView.document, let url = documentURL else { return }
        guard isDirty else {
            showToast("没有未保存的修改")
            return
        }
        if document.write(to: url) {
            isDirty = false
            statusLabel.text = "已保存"
            showToast("已保存到原文件")
        } else {
            showError("无法写入原文件，请使用“另存为”。")
        }
    }

    @objc private func returnHome() {
        guard isDirty else {
            closeDocument()
            navigateHome()
            return
        }

        let alert = UIAlertController(
            title: "未保存的修改",
            message: "返回主页前是否保存当前 PDF？",
            preferredStyle: .alert
        )
        alert.addAction(UIAlertAction(title: "取消", style: .cancel))
        alert.addAction(UIAlertAction(title: "放弃修改", style: .destructive) { [weak self] _ in
            self?.closeDocument()
            self?.navigateHome()
        })
        alert.addAction(UIAlertAction(title: "保存并返回", style: .default) { [weak self] _ in
            guard let self,
                  let document = self.pdfView.document,
                  let url = self.documentURL else { return }
            if document.write(to: url) {
                self.closeDocument()
                self.navigateHome()
            } else {
                self.showError("无法写入原文件，请先使用“另存为”。")
            }
        })
        present(alert, animated: true)
    }

    private func navigateHome() {
        navigationController?.popToRootViewController(animated: true)
    }

    private func closeDocument() {
        clearSelection()
        clearSearch()
        pdfView.document = nil
        actionUndoManager.removeAllActions()
        securityScopedURL?.stopAccessingSecurityScopedResource()
        securityScopedURL = nil
        documentURL = nil
        isDirty = false
        titleLabel.text = "PDF 阅读器"
        statusLabel.text = "打开或选择 PDF 开始阅读"
        pageLabel.text = "0 / 0"
    }

    @objc private func exportPDF() {
        guard let document = pdfView.document, let data = document.dataRepresentation() else { return }
        let base = documentURL?.deletingPathExtension().lastPathComponent ?? "PDF"
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(base)_标注_\(UUID().uuidString.prefix(8)).pdf")
        do {
            try data.write(to: url, options: .atomic)
            let picker = UIDocumentPickerViewController(forExporting: [url], asCopy: true)
            present(picker, animated: true)
        } catch {
            showError("导出失败：\(error.localizedDescription)")
        }
    }

    @objc private func handleIncomingPDF(_ notification: Notification) {
        guard let url = notification.object as? URL else { return }
        openDocument(at: url)
    }

    @objc private func toolTapped(_ sender: UIButton) {
        guard ReaderTool.allCases.indices.contains(sender.tag) else { return }
        setTool(ReaderTool.allCases[sender.tag])
    }

    private func setTool(_ tool: ReaderTool) {
        currentTool = tool
        overlay.tool = tool
        if tool != .selectInk { clearSelection() }
        for (item, button) in toolButtons {
            button.isSelected = item == tool
            var configuration = button.configuration
            configuration?.baseForegroundColor = item == tool ? .hiBrand : .secondaryLabel
            configuration?.baseBackgroundColor = item == tool ? .hiBrandContainer : .secondarySystemFill
            button.configuration = configuration
        }
    }

    @objc private func cyclePenColor() {
        penColorIndex = (penColorIndex + 1) % penColors.count
        updatePenColorButton()
    }

    private func updatePenColorButton() {
        let (color, name) = penColors[penColorIndex]
        overlay.penColor = color
        penColorButton.tintColor = color
        penColorButton.configuration?.baseForegroundColor = color
        penColorButton.accessibilityLabel = "笔色：\(name)"
    }

    @objc private func cycleSelectionColor() {
        selectionColorIndex = (selectionColorIndex + 1) % penColors.count
        updateSelectionColorButton()
        recolorSelectedInk(penColors[selectionColorIndex].0)
    }

    private func updateSelectionColorButton() {
        let (color, name) = penColors[selectionColorIndex]
        selectionColorButton.configuration?.baseForegroundColor = color
        selectionColorButton.accessibilityLabel = "所选笔画颜色：\(name)"
    }

    @objc private func toggleSelectionShape() {
        selectionShape = selectionShape == .rectangle ? .lasso : .rectangle
        overlay.selectionShape = selectionShape
        let symbol = selectionShape == .rectangle ? "rectangle.dashed" : "lasso"
        selectionShapeButton.configuration?.image = UIImage(systemName: symbol)
        selectionShapeButton.accessibilityLabel =
            selectionShape == .rectangle ? "选择模式：矩形" : "选择模式：套索"
    }

    @objc private func undoAction() {
        guard actionUndoManager.canUndo else {
            showToast("没有可撤销的操作")
            return
        }
        clearSelection()
        actionUndoManager.undo()
        markDirty()
    }

    private func setAnnotation(_ annotation: PDFAnnotation, on page: PDFPage, present: Bool) {
        if present { page.addAnnotation(annotation) } else { page.removeAnnotation(annotation) }
        actionUndoManager.registerUndo(withTarget: self) { target in
            target.setAnnotation(annotation, on: page, present: !present)
        }
        markDirty()
    }

    private func markDirty() {
        isDirty = true
        statusLabel.text = "有未保存修改"
    }

    @objc private func toggleSearch() {
        searchBar.isHidden.toggle()
        if !searchBar.isHidden { searchField.becomeFirstResponder() }
    }

    @objc private func startSearch() {
        searchField.resignFirstResponder()
        guard let query = searchField.text?.trimmingCharacters(in: .whitespacesAndNewlines),
              !query.isEmpty,
              let document = pdfView.document else { return }
        searchHits = document.findString(query, withOptions: [.caseInsensitive])
        currentSearchHit = searchHits.isEmpty ? -1 : 0
        showCurrentSearchHit()
    }

    @objc private func previousSearchHit() { stepSearch(by: -1) }
    @objc private func nextSearchHit() { stepSearch(by: 1) }

    private func stepSearch(by delta: Int) {
        guard !searchHits.isEmpty else { return }
        currentSearchHit = (currentSearchHit + delta + searchHits.count) % searchHits.count
        showCurrentSearchHit()
    }

    private func showCurrentSearchHit() {
        for (index, selection) in searchHits.enumerated() {
            selection.color = index == currentSearchHit
                ? UIColor.systemOrange.withAlphaComponent(0.55)
                : UIColor.systemYellow.withAlphaComponent(0.38)
        }
        pdfView.highlightedSelections = searchHits
        if searchHits.isEmpty {
            searchCountLabel.text = "0 条"
        } else {
            searchCountLabel.text = "\(currentSearchHit + 1) / \(searchHits.count)"
            pdfView.go(to: searchHits[currentSearchHit])
        }
        updatePageLabel()
    }

    private func clearSearch() {
        searchHits.removeAll()
        currentSearchHit = -1
        pdfView.highlightedSelections = nil
        searchCountLabel.text = nil
    }

    @objc private func previousPage() { showPage(offset: -1) }
    @objc private func nextPage() { showPage(offset: 1) }

    private func showPage(offset: Int) {
        guard let document = pdfView.document, let page = pdfView.currentPage else { return }
        let index = min(max(document.index(for: page) + offset, 0), document.pageCount - 1)
        guard let target = document.page(at: index) else { return }
        clearSelection()
        pdfView.go(to: target)
        updatePageLabel()
    }

    @objc private func fitToWidth() {
        pdfView.autoScales = true
        pdfView.scaleFactor = pdfView.scaleFactorForSizeToFit
    }

    @objc private func pageChanged() {
        clearSelection()
        updatePageLabel()
    }

    private func updatePageLabel() {
        guard let document = pdfView.document, let page = pdfView.currentPage else {
            pageLabel.text = "0 / 0"
            return
        }
        pageLabel.text = "\(document.index(for: page) + 1) / \(document.pageCount)"
    }

    private func addInk(samples: [StrokeSample]) {
        guard samples.count > 1,
              let page = pdfView.page(for: samples[0].location, nearest: true) else { return }
        let pagePoints = samples.compactMap { sample -> CGPoint? in
            guard pdfView.page(for: sample.location, nearest: true) === page else { return nil }
            return pdfView.convert(sample.location, to: page)
        }
        guard pagePoints.count > 1 else { return }
        let bounds = pagePoints.reduce(CGRect.null) { result, point in
            result.union(CGRect(origin: point, size: .zero))
        }.insetBy(dx: -4, dy: -4)

        let path = UIBezierPath()
        path.move(to: CGPoint(x: pagePoints[0].x - bounds.minX, y: pagePoints[0].y - bounds.minY))
        for point in pagePoints.dropFirst() {
            path.addLine(to: CGPoint(x: point.x - bounds.minX, y: point.y - bounds.minY))
        }

        let annotation = PDFAnnotation(bounds: bounds, forType: .ink, withProperties: nil)
        annotation.color = penColors[penColorIndex].0
        let border = PDFBorder()
        let pressure = samples.map(\.pressure).reduce(0, +) / CGFloat(samples.count)
        border.lineWidth = 1.8 + pressure * 2.4
        annotation.border = border
        annotation.add(path)
        setAnnotation(annotation, on: page, present: true)
    }

    private func handleNote(at viewPoint: CGPoint) {
        guard let page = pdfView.page(for: viewPoint, nearest: true) else { return }
        let point = pdfView.convert(viewPoint, to: page)
        if let annotation = page.annotation(at: point), annotation.type == "Text" {
            presentNoteEditor(annotation: annotation, page: page, point: point)
        } else {
            presentNoteEditor(annotation: nil, page: page, point: point)
        }
    }

    private func presentNoteEditor(annotation: PDFAnnotation?, page: PDFPage, point: CGPoint) {
        let alert = UIAlertController(
            title: annotation == nil ? "新建留言" : "编辑留言",
            message: nil,
            preferredStyle: .alert
        )
        alert.addTextField { field in
            field.placeholder = "留言内容"
            field.text = annotation?.contents
        }
        alert.addAction(UIAlertAction(title: "取消", style: .cancel))
        if let annotation {
            alert.addAction(UIAlertAction(title: "删除", style: .destructive) { [weak self] _ in
                self?.setAnnotation(annotation, on: page, present: false)
            })
        }
        alert.addAction(UIAlertAction(title: "保存", style: .default) { [weak self, weak alert] _ in
            guard let self,
                  let text = alert?.textFields?.first?.text?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !text.isEmpty else { return }
            if let annotation {
                let oldText = annotation.contents
                annotation.contents = text
                self.actionUndoManager.registerUndo(withTarget: self) { target in
                    annotation.contents = oldText
                    target.markDirty()
                }
                self.markDirty()
            } else {
                let bounds = CGRect(x: point.x - 12, y: point.y - 12, width: 24, height: 24)
                let note = PDFAnnotation(bounds: bounds, forType: .text, withProperties: nil)
                note.contents = text
                note.color = .systemYellow
                self.setAnnotation(note, on: page, present: true)
            }
        })
        present(alert, animated: true)
    }

    private func eraseInk(at viewPoint: CGPoint) {
        guard let page = pdfView.page(for: viewPoint, nearest: true) else { return }
        let point = pdfView.convert(viewPoint, to: page)
        guard let annotation = page.annotations.reversed().first(where: {
            $0.type == "Ink" && $0.bounds.insetBy(dx: -10, dy: -10).contains(point)
        }) else { return }
        setAnnotation(annotation, on: page, present: false)
    }

    private func selectInk(points: [CGPoint], shape: SelectionShape) {
        guard points.count > 1,
              let page = pdfView.page(for: points[0], nearest: true) else { return }
        let selectionRect = points.reduce(CGRect.null) { result, point in
            result.union(CGRect(origin: point, size: .zero))
        }
        selectedInk = page.annotations.filter { annotation in
            guard annotation.type == "Ink" else { return false }
            let rect = pdfView.convert(annotation.bounds, from: page)
            if shape == .rectangle { return selectionRect.intersects(rect) }
            return pointInPolygon(rect.center, polygon: points)
        }
        updateSelectionUI()
    }

    private func pointInPolygon(_ point: CGPoint, polygon: [CGPoint]) -> Bool {
        guard polygon.count > 2 else { return false }
        var inside = false
        var j = polygon.count - 1
        for i in polygon.indices {
            let a = polygon[i]
            let b = polygon[j]
            if (a.y > point.y) != (b.y > point.y),
               point.x < (b.x - a.x) * (point.y - a.y) / (b.y - a.y) + a.x {
                inside.toggle()
            }
            j = i
        }
        return inside
    }

    private func updateSelectionUI() {
        selectionBar.isHidden = selectedInk.isEmpty
        selectionCountLabel.text = "已选 \(selectedInk.count) 笔"
        guard let page = selectedInk.first?.page else {
            overlay.selectedBounds = nil
            return
        }
        overlay.selectedBounds = selectedInk.reduce(CGRect.null) { result, annotation in
            result.union(pdfView.convert(annotation.bounds, from: page))
        }
    }

    @objc private func clearSelection() {
        selectedInk.removeAll()
        selectionBar.isHidden = true
        overlay.selectedBounds = nil
    }

    @objc private func scaleSelectionUp() { transformSelectedInk(scale: 1.1, angle: 0) }
    @objc private func scaleSelectionDown() { transformSelectedInk(scale: 1 / 1.1, angle: 0) }
    @objc private func rotateSelectionLeft() { transformSelectedInk(scale: 1, angle: .pi / 12) }
    @objc private func rotateSelectionRight() { transformSelectedInk(scale: 1, angle: -.pi / 12) }

    @objc private func deleteSelection() {
        guard !selectedInk.isEmpty else { return }
        actionUndoManager.beginUndoGrouping()
        for annotation in selectedInk {
            if let page = annotation.page { setAnnotation(annotation, on: page, present: false) }
        }
        actionUndoManager.endUndoGrouping()
        clearSelection()
    }

    private func recolorSelectedInk(_ color: UIColor) {
        replaceSelectedInk(scale: 1, angle: 0, color: color)
    }

    private func transformSelectedInk(scale: CGFloat, angle: CGFloat) {
        replaceSelectedInk(scale: scale, angle: angle, color: nil)
    }

    private func replaceSelectedInk(scale: CGFloat, angle: CGFloat, color: UIColor?) {
        guard !selectedInk.isEmpty else { return }
        let union = selectedInk.reduce(CGRect.null) { $0.union($1.bounds) }
        let center = CGPoint(x: union.midX, y: union.midY)
        var transform = CGAffineTransform(translationX: center.x, y: center.y)
        transform = transform.rotated(by: angle).scaledBy(x: scale, y: scale)
        transform = transform.translatedBy(x: -center.x, y: -center.y)

        actionUndoManager.beginUndoGrouping()
        var replacements: [PDFAnnotation] = []
        for annotation in selectedInk {
            guard let page = annotation.page,
                  let replacement = rebuiltInk(annotation, transform: transform, color: color) else { continue }
            setAnnotation(annotation, on: page, present: false)
            setAnnotation(replacement, on: page, present: true)
            replacements.append(replacement)
        }
        actionUndoManager.endUndoGrouping()
        selectedInk = replacements
        updateSelectionUI()
    }

    private func rebuiltInk(
        _ annotation: PDFAnnotation,
        transform: CGAffineTransform,
        color: UIColor?
    ) -> PDFAnnotation? {
        guard let paths = annotation.paths, !paths.isEmpty else { return nil }
        var absolutePaths: [UIBezierPath] = []
        var combined = CGRect.null

        for source in paths {
            var toPage = CGAffineTransform(
                translationX: annotation.bounds.minX,
                y: annotation.bounds.minY
            )
            guard let pagePath = source.cgPath.copy(
                using: &toPage
            ) else { continue }
            let path = UIBezierPath(cgPath: pagePath)
            path.apply(transform)
            absolutePaths.append(path)
            combined = combined.union(path.bounds)
        }
        guard !absolutePaths.isEmpty, !combined.isNull else { return nil }

        let lineWidth = annotation.border?.lineWidth ?? 3
        let bounds = combined.insetBy(dx: -(lineWidth + 2), dy: -(lineWidth + 2))
        let replacement = PDFAnnotation(bounds: bounds, forType: .ink, withProperties: nil)
        replacement.color = color ?? annotation.color
        let border = PDFBorder()
        border.lineWidth = lineWidth * max(0.2, transform.scaleMagnitude)
        replacement.border = border

        for path in absolutePaths {
            var relative = CGAffineTransform(translationX: -bounds.minX, y: -bounds.minY)
            if let relativePath = path.cgPath.copy(using: &relative) {
                replacement.add(UIBezierPath(cgPath: relativePath))
            }
        }
        return replacement
    }

    private func showError(_ message: String) {
        let alert = UIAlertController(title: "操作失败", message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "确定", style: .default))
        present(alert, animated: true)
    }

    private func showToast(_ message: String) {
        let alert = UIAlertController(title: nil, message: message, preferredStyle: .alert)
        present(alert, animated: true)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak alert] in
            alert?.dismiss(animated: true)
        }
    }
}

extension ReaderViewController: DrawingOverlayViewDelegate {
    func overlay(_ overlay: DrawingOverlayView, didFinishStroke samples: [StrokeSample]) {
        addInk(samples: samples)
    }

    func overlay(_ overlay: DrawingOverlayView, didTap location: CGPoint) {
        handleNote(at: location)
    }

    func overlay(_ overlay: DrawingOverlayView, didErase location: CGPoint) {
        eraseInk(at: location)
    }

    func overlay(
        _ overlay: DrawingOverlayView,
        didFinishSelection points: [CGPoint],
        shape: SelectionShape
    ) {
        selectInk(points: points, shape: shape)
    }
}

extension ReaderViewController: UIDocumentPickerDelegate {
    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        guard let url = urls.first else { return }
        openDocument(at: url)
    }
}

extension ReaderViewController: UITextFieldDelegate {
    func textFieldShouldReturn(_ textField: UITextField) -> Bool {
        startSearch()
        return true
    }
}

private extension CGRect {
    var center: CGPoint { CGPoint(x: midX, y: midY) }
}

private extension CGAffineTransform {
    var scaleMagnitude: CGFloat { sqrt(a * a + c * c) }
}
