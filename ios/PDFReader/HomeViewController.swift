import AVFoundation
import PDFKit
import UIKit
import UniformTypeIdentifiers
import Vision

@MainActor
final class HomeViewController: UIViewController, UIDocumentPickerDelegate {
    private let contentStack = UIStackView()
    private var pendingFeature: Feature?

    private enum Feature {
        case reader
        case pdfToImages
        case extract
        case imagesToPDF
        case bookmarks
        case ocr

        var title: String {
            switch self {
            case .reader: return "PDF 阅读器"
            case .pdfToImages: return "PDF 转图片"
            case .extract: return "页码节选"
            case .imagesToPDF: return "图片转 PDF"
            case .bookmarks: return "自动书签"
            case .ocr: return "PDF OCR"
            }
        }

        var subtitle: String {
            switch self {
            case .reader: return "预览、手写批注、留言、搜索和标注变换"
            case .pdfToImages: return "将 PDF 页面导出为 PNG 图片"
            case .extract: return "按页码范围导出新的 PDF"
            case .imagesToPDF: return "选择多张图片合成为 PDF"
            case .bookmarks: return "识别章节标题并生成可跳转目录"
            case .ocr: return "识别扫描页文字并生成可搜索 PDF"
            }
        }

        var symbol: String {
            switch self {
            case .reader: return "book.closed"
            case .pdfToImages: return "photo.on.rectangle.angled"
            case .extract: return "scissors"
            case .imagesToPDF: return "photo.stack"
            case .bookmarks: return "list.bullet.rectangle"
            case .ocr: return "text.viewfinder"
            }
        }

        var tint: UIColor {
            switch self {
            case .reader: return .hiBrand
            case .pdfToImages: return .systemOrange
            case .extract: return .systemPurple
            case .imagesToPDF: return .systemGreen
            case .bookmarks: return .systemIndigo
            case .ocr: return .systemTeal
            }
        }
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        navigationController?.setNavigationBarHidden(true, animated: false)
        view.backgroundColor = .hiCanvas
        buildInterface()
    }

    func openDocument(at url: URL) {
        openReader(url: url)
    }

    private func buildInterface() {
        let scroll = UIScrollView()
        scroll.alwaysBounceVertical = true
        scroll.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(scroll)
        NSLayoutConstraint.activate([
            scroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scroll.topAnchor.constraint(equalTo: view.topAnchor),
            scroll.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])

        contentStack.axis = .vertical
        contentStack.spacing = 18
        contentStack.layoutMargins = UIEdgeInsets(top: 28, left: 22, bottom: 28, right: 22)
        contentStack.isLayoutMarginsRelativeArrangement = true
        contentStack.translatesAutoresizingMaskIntoConstraints = false
        scroll.addSubview(contentStack)
        NSLayoutConstraint.activate([
            contentStack.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor),
            contentStack.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor),
            contentStack.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor),
            contentStack.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor),
            contentStack.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor),
        ])

        let eyebrow = UILabel()
        eyebrow.text = "PDF 工具箱"
        eyebrow.textColor = .hiBrand
        eyebrow.font = .systemFont(ofSize: 15, weight: .semibold)
        contentStack.addArrangedSubview(eyebrow)

        let title = UILabel()
        title.text = "PDF 转换工具"
        title.font = .systemFont(ofSize: 34, weight: .bold)
        title.textColor = .label
        contentStack.addArrangedSubview(title)

        let summary = UILabel()
        summary.text = "在 iPhone 和 iPad 上阅读、整理和导出 PDF。"
        summary.numberOfLines = 0
        summary.font = .preferredFont(forTextStyle: .subheadline)
        summary.textColor = .secondaryLabel
        contentStack.addArrangedSubview(summary)

        addSection("阅读与转换", features: [.reader, .pdfToImages, .extract, .imagesToPDF])
        addSection("智能与整理", features: [.bookmarks, .ocr])

        let footer = UILabel()
        footer.text = "iOS 原生版 · 支持深色模式、Apple Pencil 与 Liquid Glass"
        footer.textColor = .tertiaryLabel
        footer.font = .systemFont(ofSize: 12)
        footer.textAlignment = .center
        footer.numberOfLines = 0
        contentStack.addArrangedSubview(footer)
    }

    private func addSection(_ title: String, features: [Feature]) {
        let heading = UILabel()
        heading.text = title
        heading.font = .systemFont(ofSize: 18, weight: .semibold)
        heading.textColor = .label
        contentStack.addArrangedSubview(heading)

        for feature in features {
            let panel = GlassPanelView(cornerRadius: 20)
            panel.heightAnchor.constraint(greaterThanOrEqualToConstant: 92).isActive = true

            let button = UIButton(type: .system)
            button.accessibilityLabel = "(feature.title)：(feature.subtitle)"
            button.addAction(UIAction { [weak self] _ in
                self?.select(feature)
            }, for: .touchUpInside)
            button.translatesAutoresizingMaskIntoConstraints = false
            panel.contentView.addSubview(button)
            NSLayoutConstraint.activate([
                button.leadingAnchor.constraint(equalTo: panel.contentView.leadingAnchor),
                button.trailingAnchor.constraint(equalTo: panel.contentView.trailingAnchor),
                button.topAnchor.constraint(equalTo: panel.contentView.topAnchor),
                button.bottomAnchor.constraint(equalTo: panel.contentView.bottomAnchor),
            ])

            let icon = UIImageView(image: UIImage(systemName: feature.symbol))
            icon.tintColor = feature.tint
            icon.contentMode = .scaleAspectFit
            icon.translatesAutoresizingMaskIntoConstraints = false
            button.addSubview(icon)

            let name = UILabel()
            name.text = feature.title
            name.font = .systemFont(ofSize: 17, weight: .semibold)
            name.textColor = .label
            name.translatesAutoresizingMaskIntoConstraints = false
            button.addSubview(name)

            let detail = UILabel()
            detail.text = feature.subtitle
            detail.font = .systemFont(ofSize: 13)
            detail.textColor = .secondaryLabel
            detail.numberOfLines = 2
            detail.translatesAutoresizingMaskIntoConstraints = false
            button.addSubview(detail)

            let arrow = UIImageView(image: UIImage(systemName: "chevron.right"))
            arrow.tintColor = .tertiaryLabel
            arrow.translatesAutoresizingMaskIntoConstraints = false
            button.addSubview(arrow)

            NSLayoutConstraint.activate([
                icon.leadingAnchor.constraint(equalTo: button.leadingAnchor, constant: 20),
                icon.centerYAnchor.constraint(equalTo: button.centerYAnchor),
                icon.widthAnchor.constraint(equalToConstant: 30),
                icon.heightAnchor.constraint(equalToConstant: 30),
                name.leadingAnchor.constraint(equalTo: icon.trailingAnchor, constant: 16),
                name.trailingAnchor.constraint(lessThanOrEqualTo: arrow.leadingAnchor, constant: -12),
                name.topAnchor.constraint(equalTo: button.topAnchor, constant: 19),
                detail.leadingAnchor.constraint(equalTo: name.leadingAnchor),
                detail.trailingAnchor.constraint(lessThanOrEqualTo: arrow.leadingAnchor, constant: -12),
                detail.topAnchor.constraint(equalTo: name.bottomAnchor, constant: 4),
                detail.bottomAnchor.constraint(lessThanOrEqualTo: button.bottomAnchor, constant: -16),
                arrow.trailingAnchor.constraint(equalTo: button.trailingAnchor, constant: -20),
                arrow.centerYAnchor.constraint(equalTo: button.centerYAnchor),
                arrow.widthAnchor.constraint(equalToConstant: 12),
            ])
            contentStack.addArrangedSubview(panel)
        }
    }

    private func select(_ feature: Feature) {
        switch feature {
        case .reader:
            openReader(url: nil)
        case .pdfToImages, .extract, .imagesToPDF, .bookmarks, .ocr:
            pendingFeature = feature
            let types: [UTType] = feature == .imagesToPDF ? [.image] : [.pdf]
            let picker = UIDocumentPickerViewController(forOpeningContentTypes: types, asCopy: false)
            picker.allowsMultipleSelection = feature == .imagesToPDF
            picker.delegate = self
            present(picker, animated: true)
        }
    }

    private func openReader(url: URL?) {
        let reader = ReaderViewController()
        navigationController?.pushViewController(reader, animated: true)
        if let url {
            DispatchQueue.main.async { reader.openDocument(at: url) }
        }
    }

    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        guard let feature = pendingFeature else { return }
        pendingFeature = nil
        switch feature {
        case .pdfToImages: convertPDFToImages(urls[0])
        case .extract: extractPDF(urls[0])
        case .imagesToPDF: convertImagesToPDF(urls)
        case .bookmarks: generateAutomaticBookmarks(urls[0])
        case .ocr: recognizeTextInPDF(urls[0])
        case .reader: break
        }
    }

    private func convertPDFToImages(_ url: URL) {
        guard let document = PDFDocument(url: url) else {
            showInfo(title: "无法打开 PDF", message: "请确认文件内容有效。")
            return
        }
        let folder = FileManager.default.temporaryDirectory
            .appendingPathComponent("PDFImages_\(UUID().uuidString)", isDirectory: true)
        do {
            try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
            var files: [URL] = []
            for index in 0..<document.pageCount {
                guard let page = document.page(at: index) else { continue }
                let image = page.thumbnail(of: CGSize(width: 1800, height: 2400), for: .mediaBox)
                let output = folder.appendingPathComponent(String(format: "page-%03d.png", index + 1))
                guard let data = image.pngData() else { continue }
                try data.write(to: output, options: .atomic)
                files.append(output)
            }
            export(files, message: "已生成 (files.count) 张 PNG 图片")
        } catch { showInfo(title: "导出失败", message: error.localizedDescription) }
    }

    private func extractPDF(_ url: URL) {
        guard let session = PDFReviewSession(url: url), session.document.pageCount > 0 else {
            showInfo(title: "无法打开 PDF", message: "请确认文件有效且至少包含一页。")
            return
        }
        presentReview(ExtractPreviewViewController(session: session, sourceName: url.deletingPathExtension().lastPathComponent))
    }

    private func parsePages(_ text: String, count: Int) -> [Int]? {
        var result = Set<Int>()
        for part in text.split(separator: ",") {
            let values = part.split(separator: "-").compactMap { Int($0.trimmingCharacters(in: .whitespaces)) }
            guard let first = values.first else { return nil }
            let last = values.count > 1 ? values[1] : first
            guard first >= 1, last >= first, last <= count else { return nil }
            for page in first...last { result.insert(page - 1) }
        }
        return result.sorted()
    }

    private func convertImagesToPDF(_ urls: [URL]) {
        let output = FileManager.default.temporaryDirectory.appendingPathComponent("图片合成.pdf")
        let renderer = UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 595, height: 842))
        do {
            try renderer.writePDF(to: output) { context in
                for url in urls {
                    guard let image = UIImage(contentsOfFile: url.path) else { continue }
                    context.beginPage()
                    let bounds = AVMakeRect(aspectRatio: image.size, insideRect: CGRect(x: 24, y: 24, width: 547, height: 794))
                    image.draw(in: bounds)
                }
            }
            export([output], message: "已生成图片合成 PDF")
        } catch { showInfo(title: "导出失败", message: error.localizedDescription) }
    }

    private struct OCRPageResult {
        let image: UIImage
        let lines: [(text: String, box: CGRect)]
    }

    private func recognizeTextInPDF(_ url: URL) {
        let progress = UIAlertController(
            title: "正在识别 PDF",
            message: "扫描页较多时可能需要一些时间，请稍候。",
            preferredStyle: .alert
        )
        present(progress, animated: true)

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            let result = Self.makeSearchablePDF(from: url)
            DispatchQueue.main.async {
                progress.dismiss(animated: true) {
                    guard let self else { return }
                    switch result {
                    case let .success(output):
                        self.export([output], message: "OCR 已完成")
                    case let .failure(error):
                        self.showInfo(title: "OCR 失败", message: error.localizedDescription)
                    }
                }
            }
        }
    }

    private nonisolated static func makeSearchablePDF(from url: URL) -> Result<URL, Error> {
        enum OCRFailure: LocalizedError {
            case invalidDocument
            case noPages
            case noRecognizedText
            case couldNotWrite

            var errorDescription: String? {
                switch self {
                case .invalidDocument: return "无法打开这个 PDF。"
                case .noPages: return "PDF 没有可识别的页面。"
                case .noRecognizedText: return "没有识别到文字，请确认页面清晰且包含文字。"
                case .couldNotWrite: return "无法生成 OCR 结果文件。"
                }
            }
        }

        guard let document = PDFDocument(url: url) else { return .failure(OCRFailure.invalidDocument) }
        guard document.pageCount > 0 else { return .failure(OCRFailure.noPages) }

        var pages: [OCRPageResult] = []
        var recognizedCount = 0
        for index in 0..<document.pageCount {
            guard let page = document.page(at: index) else { continue }
            let image = page.thumbnail(of: CGSize(width: 1800, height: 2400), for: .mediaBox)
            guard let cgImage = image.cgImage else { continue }
            let request = VNRecognizeTextRequest()
            request.recognitionLevel = .accurate
            request.usesLanguageCorrection = true
            request.recognitionLanguages = ["zh-Hans", "en-US"]
            do {
                let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
                try handler.perform([request])
            } catch {
                continue
            }
            let lines = (request.results ?? []).compactMap { observation -> (String, CGRect)? in
                guard let candidate = observation.topCandidates(1).first,
                      !candidate.string.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                    return nil
                }
                return (candidate.string, observation.boundingBox)
            }
            recognizedCount += lines.count
            pages.append(OCRPageResult(image: image, lines: lines))
        }

        guard recognizedCount > 0 else { return .failure(OCRFailure.noRecognizedText) }
        let output = FileManager.default.temporaryDirectory
            .appendingPathComponent("OCR_\(url.deletingPathExtension().lastPathComponent).pdf")
        let pageBounds = document.page(at: 0)?.bounds(for: .mediaBox) ?? CGRect(x: 0, y: 0, width: 595, height: 842)
        let renderer = UIGraphicsPDFRenderer(bounds: pageBounds)
        do {
            try renderer.writePDF(to: output) { context in
                for page in pages {
                    context.beginPage()
                    page.image.draw(in: pageBounds)
                    for line in page.lines {
                        let box = line.box
                        let rect = CGRect(
                            x: pageBounds.minX + box.minX * pageBounds.width,
                            y: pageBounds.minY + (1 - box.maxY) * pageBounds.height,
                            width: max(1, box.width * pageBounds.width),
                            height: max(4, box.height * pageBounds.height)
                        )
                        let fontSize = max(4, min(18, rect.height * 0.9))
                        let attributes: [NSAttributedString.Key: Any] = [
                            .font: UIFont.systemFont(ofSize: fontSize),
                            .foregroundColor: UIColor.white.withAlphaComponent(0.01),
                        ]
                        (line.text as NSString).draw(in: rect, withAttributes: attributes)
                    }
                }
            }
            return .success(output)
        } catch {
            return .failure(error)
        }
    }

    private func generateAutomaticBookmarks(_ url: URL) {
        guard let session = PDFReviewSession(url: url), session.document.pageCount > 0 else {
            showInfo(title: "无法生成书签", message: "请确认 PDF 内容有效。")
            return
        }

        var entries: [BookmarkPreviewViewController.Entry] = []
        for index in 0..<session.document.pageCount {
            guard let page = session.document.page(at: index) else { continue }
            for title in Self.headingCandidates(from: page.string ?? "").prefix(3) {
                let level = Self.headingLevel(for: title)
                entries.append(.init(title: title, pageIndex: index, level: level))
            }
        }
        guard !entries.isEmpty else {
            showInfo(title: "没有识别到目录", message: "这份 PDF 没有可提取的文字标题。扫描件请先运行 OCR，再生成书签。")
            return
        }
        presentReview(BookmarkPreviewViewController(
            session: session,
            sourceName: url.deletingPathExtension().lastPathComponent,
            entries: entries
        ))
    }

    private nonisolated static func headingCandidates(from text: String) -> [String] {
        text.split(whereSeparator: { $0.isNewline }).compactMap { rawLine in
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.isEmpty, line.count <= 80 else { return nil }
            let isNumbered = line.range(of: "^(第[一二三四五六七八九十百千万0-9]+[章节篇部]|Chapter\\s+[0-9]+|[0-9]+(\\.[0-9]+)*\\s+)", options: .regularExpression) != nil
            let isShortTitle = line.count <= 24 && !line.contains("。") && !line.contains("，") && !line.contains(",")
            return isNumbered || isShortTitle ? line : nil
        }
    }

    private nonisolated static func headingLevel(for title: String) -> Int {
        if let range = title.range(of: "^[0-9]+(\\.[0-9]+)*", options: .regularExpression) {
            return min(6, max(1, title[range].filter { $0 == "." }.count + 1))
        }
        if title.range(of: "^Chapter\\s+[0-9]+", options: [.regularExpression, .caseInsensitive]) != nil {
            return 1
        }
        return 1
    }

    private func presentReview(_ controller: UIViewController) {
        let navigation = UINavigationController(rootViewController: controller)
        navigation.modalPresentationStyle = .pageSheet
        if let sheet = navigation.sheetPresentationController {
            sheet.detents = [.large()]
            sheet.prefersGrabberVisible = true
            sheet.preferredCornerRadius = 28
        }
        present(navigation, animated: true)
    }

    private func export(_ urls: [URL], message: String) {
        let picker = UIDocumentPickerViewController(forExporting: urls, asCopy: true)
        present(picker, animated: true)
    }

    private func showInfo(title: String, message: String) {
        let alert = UIAlertController(title: title, message: message, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "确定", style: .default))
        present(alert, animated: true)
    }
}

@MainActor
private final class PDFReviewSession {
    let document: PDFDocument
    private let url: URL
    private let hasSecurityScope: Bool

    init?(url: URL) {
        self.url = url
        hasSecurityScope = url.startAccessingSecurityScopedResource()
        guard let document = PDFDocument(url: url) else {
            if hasSecurityScope { url.stopAccessingSecurityScopedResource() }
            return nil
        }
        self.document = document
    }

    deinit {
        if hasSecurityScope { url.stopAccessingSecurityScopedResource() }
    }
}

@MainActor
private final class BookmarkPreviewViewController: UITableViewController {
    struct Entry: Identifiable {
        let id = UUID()
        var title: String
        var pageIndex: Int
        var level: Int
    }

    private let session: PDFReviewSession
    private let sourceName: String
    private var entries: [Entry]
    private let thumbnailCache = NSCache<NSNumber, UIImage>()
    private var activePicker: UIDocumentPickerViewController?

    init(session: PDFReviewSession, sourceName: String, entries: [Entry]) {
        self.session = session
        self.sourceName = sourceName
        self.entries = entries
        super.init(style: .insetGrouped)
        thumbnailCache.countLimit = 80
        title = "目录预览"
        navigationItem.prompt = "\(entries.count) 个标题 · 点按编辑，左滑删除"
        navigationItem.leftBarButtonItem = UIBarButtonItem(
            systemItem: .close,
            primaryAction: UIAction { [weak self] _ in self?.dismiss(animated: true) }
        )
        navigationItem.rightBarButtonItems = [
            UIBarButtonItem(title: "导出", image: UIImage(systemName: "square.and.arrow.up"),
                            primaryAction: UIAction { [weak self] _ in self?.exportBookmarks() }),
            UIBarButtonItem(barButtonSystemItem: .add, target: self, action: #selector(addBookmark)),
        ]
        tableView.rowHeight = 84
        tableView.register(BookmarkPreviewCell.self, forCellReuseIdentifier: BookmarkPreviewCell.reuseID)
        tableView.backgroundColor = .systemGroupedBackground
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        navigationController?.setToolbarHidden(true, animated: false)
    }

    override func tableView(_ tableView: UITableView, numberOfRowsInSection section: Int) -> Int { entries.count }

    override func tableView(_ tableView: UITableView, cellForRowAt indexPath: IndexPath) -> UITableViewCell {
        let cell = tableView.dequeueReusableCell(withIdentifier: BookmarkPreviewCell.reuseID, for: indexPath) as! BookmarkPreviewCell
        let entry = entries[indexPath.row]
        let thumbnail = thumbnailCache.object(forKey: NSNumber(value: entry.pageIndex)) ??
            session.document.page(at: entry.pageIndex)?.thumbnail(of: CGSize(width: 120, height: 160), for: .mediaBox)
        if let thumbnail { thumbnailCache.setObject(thumbnail, forKey: NSNumber(value: entry.pageIndex)) }
        cell.configure(entry: entry, thumbnail: thumbnail)
        return cell
    }

    override func tableView(_ tableView: UITableView, didSelectRowAt indexPath: IndexPath) {
        tableView.deselectRow(at: indexPath, animated: true)
        editBookmark(at: indexPath.row)
    }

    override func tableView(
        _ tableView: UITableView,
        trailingSwipeActionsConfigurationForRowAt indexPath: IndexPath
    ) -> UISwipeActionsConfiguration? {
        let delete = UIContextualAction(style: .destructive, title: "删除") { [weak self] _, _, done in
            guard let self else { done(false); return }
            self.entries.remove(at: indexPath.row)
            tableView.deleteRows(at: [indexPath], with: .automatic)
            self.navigationItem.prompt = "\(self.entries.count) 个标题 · 点按编辑，左滑删除"
            done(true)
        }
        return UISwipeActionsConfiguration(actions: [delete])
    }

    @objc private func addBookmark() {
        presentBookmarkEditor(entry: Entry(title: "新书签", pageIndex: 0, level: 1), isNew: true)
    }

    private func editBookmark(at index: Int) {
        presentBookmarkEditor(entry: entries[index], isNew: false, originalIndex: index)
    }

    private func presentBookmarkEditor(entry: Entry, isNew: Bool, originalIndex: Int? = nil) {
        let alert = UIAlertController(title: isNew ? "添加书签" : "编辑书签", message: nil, preferredStyle: .alert)
        alert.addTextField { field in
            field.text = entry.title
            field.placeholder = "标题"
            field.clearButtonMode = .whileEditing
        }
        alert.addTextField { field in
            field.text = String(entry.pageIndex + 1)
            field.placeholder = "页码"
            field.keyboardType = .numberPad
        }
        alert.addTextField { field in
            field.text = String(entry.level)
            field.placeholder = "层级（1–6）"
            field.keyboardType = .numberPad
        }
        alert.addAction(UIAlertAction(title: "取消", style: .cancel))
        alert.addAction(UIAlertAction(title: isNew ? "添加" : "保存", style: .default) { [weak self, weak alert] _ in
            guard let self,
                  let fields = alert?.textFields,
                  let title = fields[0].text?.trimmingCharacters(in: .whitespacesAndNewlines),
                  !title.isEmpty,
                  let page = Int(fields[1].text ?? ""),
                  (1...self.session.document.pageCount).contains(page),
                  let level = Int(fields[2].text ?? ""), (1...6).contains(level) else {
                self?.showMessage("内容无效", detail: "请填写标题，并输入有效页码及 1 到 6 的层级。")
                return
            }
            var updated = entry
            updated.title = title
            updated.pageIndex = page - 1
            updated.level = level
            if let originalIndex {
                self.entries[originalIndex] = updated
                self.tableView.reloadRows(at: [IndexPath(row: originalIndex, section: 0)], with: .automatic)
            } else {
                let insertion = self.entries.firstIndex(where: { $0.pageIndex > updated.pageIndex }) ?? self.entries.count
                self.entries.insert(updated, at: insertion)
                self.tableView.insertRows(at: [IndexPath(row: insertion, section: 0)], with: .automatic)
            }
            self.navigationItem.prompt = "\(self.entries.count) 个标题 · 点按编辑，左滑删除"
        })
        present(alert, animated: true)
    }

    private func exportBookmarks() {
        guard !entries.isEmpty else {
            showMessage("没有书签", detail: "请至少保留一条目录条目后再导出。")
            return
        }
        let root = PDFOutline()
        var parents: [Int: PDFOutline] = [:]
        for entry in entries {
            guard let page = session.document.page(at: entry.pageIndex) else { continue }
            let level = min(6, max(1, entry.level))
            let node = PDFOutline()
            node.label = entry.title
            node.destination = PDFDestination(page: page, at: CGPoint(x: 0, y: page.bounds(for: .mediaBox).maxY))
            let parent = parents[level - 1] ?? root
            parent.insertChild(node, at: parent.numberOfChildren)
            parents[level] = node
            parents = parents.filter { $0.key <= level }
        }
        session.document.outlineRoot = root
        let output = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(sourceName)_带书签_\(UUID().uuidString.prefix(6)).pdf")
        guard session.document.write(to: output) else {
            showMessage("导出失败", detail: "无法写入带书签的 PDF。")
            return
        }
        let picker = UIDocumentPickerViewController(forExporting: [output], asCopy: true)
        activePicker = picker
        picker.delegate = self
        present(picker, animated: true)
    }

    private func showMessage(_ title: String, detail: String) {
        let alert = UIAlertController(title: title, message: detail, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "好", style: .default))
        present(alert, animated: true)
    }
}

extension BookmarkPreviewViewController: UIDocumentPickerDelegate {
    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        dismiss(animated: true)
    }

    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) { activePicker = nil }
}

@MainActor
private final class BookmarkPreviewCell: UITableViewCell {
    static let reuseID = "BookmarkPreviewCell"
    private let pageImageView = UIImageView()
    private let titleLabel = UILabel()
    private let detailLabel = UILabel()
    private let stack = UIStackView()

    override init(style: UITableViewCell.CellStyle, reuseIdentifier: String?) {
        super.init(style: style, reuseIdentifier: reuseIdentifier)
        selectionStyle = .default
        accessoryType = .disclosureIndicator
        pageImageView.contentMode = .scaleAspectFit
        pageImageView.backgroundColor = .secondarySystemGroupedBackground
        pageImageView.layer.cornerRadius = 6
        pageImageView.clipsToBounds = true
        pageImageView.translatesAutoresizingMaskIntoConstraints = false
        titleLabel.font = .systemFont(ofSize: 16, weight: .semibold)
        titleLabel.numberOfLines = 2
        detailLabel.font = .systemFont(ofSize: 12)
        detailLabel.textColor = .secondaryLabel
        stack.axis = .vertical
        stack.spacing = 5
        stack.isLayoutMarginsRelativeArrangement = true
        stack.addArrangedSubview(titleLabel)
        stack.addArrangedSubview(detailLabel)
        stack.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(pageImageView)
        contentView.addSubview(stack)
        NSLayoutConstraint.activate([
            pageImageView.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 16),
            pageImageView.centerYAnchor.constraint(equalTo: contentView.centerYAnchor),
            pageImageView.widthAnchor.constraint(equalToConstant: 46),
            pageImageView.heightAnchor.constraint(equalToConstant: 62),
            stack.leadingAnchor.constraint(equalTo: pageImageView.trailingAnchor, constant: 12),
            stack.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -28),
            stack.centerYAnchor.constraint(equalTo: contentView.centerYAnchor),
        ])
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func configure(entry: BookmarkPreviewViewController.Entry, thumbnail: UIImage?) {
        pageImageView.image = thumbnail
        titleLabel.text = entry.title
        detailLabel.text = "第 \(entry.pageIndex + 1) 页 · 层级 \(entry.level)"
        stack.layoutMargins = UIEdgeInsets(top: 0, left: CGFloat(max(0, entry.level - 1) * 12), bottom: 0, right: 0)
    }
}

@MainActor
private final class ExtractPreviewViewController: UIViewController, UICollectionViewDataSource, UICollectionViewDelegateFlowLayout {
    private let session: PDFReviewSession
    private let sourceName: String
    private var selectedPages = Set<Int>()
    private let thumbnailCache = NSCache<NSNumber, UIImage>()
    private let collectionView: UICollectionView
    private let countItem = UIBarButtonItem(title: "尚未选择页面", style: .plain, target: nil, action: nil)

    init(session: PDFReviewSession, sourceName: String) {
        self.session = session
        self.sourceName = sourceName
        let layout = UICollectionViewFlowLayout()
        layout.minimumInteritemSpacing = 12
        layout.minimumLineSpacing = 16
        collectionView = UICollectionView(frame: .zero, collectionViewLayout: layout)
        super.init(nibName: nil, bundle: nil)
        thumbnailCache.countLimit = 100
        title = "节选预览"
        navigationItem.prompt = "点按页面卡片选择要导出的页面"
        navigationItem.leftBarButtonItem = UIBarButtonItem(
            systemItem: .close,
            primaryAction: UIAction { [weak self] _ in self?.dismiss(animated: true) }
        )
        navigationItem.rightBarButtonItem = UIBarButtonItem(
            title: "页码范围",
            image: UIImage(systemName: "list.number"),
            primaryAction: UIAction { [weak self] _ in self?.enterPageRange() }
        )
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .systemGroupedBackground
        collectionView.backgroundColor = .clear
        collectionView.contentInset = UIEdgeInsets(top: 12, left: 16, bottom: 16, right: 16)
        collectionView.dataSource = self
        collectionView.delegate = self
        collectionView.register(ExtractPageCell.self, forCellWithReuseIdentifier: ExtractPageCell.reuseID)
        collectionView.translatesAutoresizingMaskIntoConstraints = false
        view.addSubview(collectionView)
        NSLayoutConstraint.activate([
            collectionView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            collectionView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            collectionView.topAnchor.constraint(equalTo: view.safeAreaLayoutGuide.topAnchor),
            collectionView.bottomAnchor.constraint(equalTo: view.safeAreaLayoutGuide.bottomAnchor),
        ])
        toolbarItems = [
            UIBarButtonItem(title: "全选", style: .plain, target: self, action: #selector(selectAllPages)),
            UIBarButtonItem(title: "清除", style: .plain, target: self, action: #selector(clearSelection)),
            UIBarButtonItem(systemItem: .flexibleSpace),
            countItem,
            UIBarButtonItem(systemItem: .flexibleSpace),
            UIBarButtonItem(title: "导出 PDF", image: UIImage(systemName: "square.and.arrow.up"),
                            primaryAction: UIAction { [weak self] _ in self?.exportSelection() }),
        ]
        navigationController?.setToolbarHidden(false, animated: false)
        updateCount()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        guard let layout = collectionView.collectionViewLayout as? UICollectionViewFlowLayout else { return }
        let columns = max(2, min(5, Int(collectionView.bounds.width / 190)))
        let spacing = layout.minimumInteritemSpacing
        let available = collectionView.bounds.width - collectionView.contentInset.left - collectionView.contentInset.right
        let width = floor((available - CGFloat(columns - 1) * spacing) / CGFloat(columns))
        let size = CGSize(width: width, height: width * 1.16)
        if layout.itemSize != size { layout.itemSize = size; layout.invalidateLayout() }
    }

    func collectionView(_ collectionView: UICollectionView, numberOfItemsInSection section: Int) -> Int {
        session.document.pageCount
    }

    func collectionView(_ collectionView: UICollectionView, cellForItemAt indexPath: IndexPath) -> UICollectionViewCell {
        let cell = collectionView.dequeueReusableCell(withReuseIdentifier: ExtractPageCell.reuseID, for: indexPath) as! ExtractPageCell
        let index = indexPath.item
        let key = NSNumber(value: index)
        let thumbnail = thumbnailCache.object(forKey: key) ??
            session.document.page(at: index)?.thumbnail(of: CGSize(width: 320, height: 420), for: .mediaBox)
        if let thumbnail { thumbnailCache.setObject(thumbnail, forKey: key) }
        cell.configure(pageNumber: index + 1, thumbnail: thumbnail, selected: selectedPages.contains(index))
        return cell
    }

    func collectionView(_ collectionView: UICollectionView, didSelectItemAt indexPath: IndexPath) {
        let page = indexPath.item
        if selectedPages.contains(page) { selectedPages.remove(page) } else { selectedPages.insert(page) }
        collectionView.reloadItems(at: [indexPath])
        updateCount()
    }

    @objc private func selectAllPages() {
        selectedPages = Set(0..<session.document.pageCount)
        collectionView.reloadData()
        updateCount()
    }

    @objc private func clearSelection() {
        selectedPages.removeAll()
        collectionView.reloadData()
        updateCount()
    }

    private func enterPageRange() {
        let alert = UIAlertController(title: "选择页码范围", message: "例如 1-3,5。应用后可继续点选缩略图。", preferredStyle: .alert)
        alert.addTextField { field in
            field.placeholder = "1-3,5"
            field.keyboardType = .numbersAndPunctuation
            field.autocorrectionType = .no
        }
        alert.addAction(UIAlertAction(title: "取消", style: .cancel))
        alert.addAction(UIAlertAction(title: "应用", style: .default) { [weak self, weak alert] _ in
            guard let self, let text = alert?.textFields?.first?.text,
                  let pages = self.parsePages(text, count: self.session.document.pageCount) else {
                self?.showMessage("页码范围无效", detail: "请输入有效范围，例如 1-3,5。")
                return
            }
            self.selectedPages = Set(pages)
            self.collectionView.reloadData()
            self.updateCount()
        })
        present(alert, animated: true)
    }

    private func parsePages(_ text: String, count: Int) -> [Int]? {
        let parts = text.split(separator: ",", omittingEmptySubsequences: false)
        guard !parts.isEmpty else { return nil }
        var pages = Set<Int>()
        for part in parts {
            let values = part.split(separator: "-", omittingEmptySubsequences: false)
                .map { Int($0.trimmingCharacters(in: .whitespaces)) }
            guard values.count <= 2, let firstValue = values.first, let first = firstValue,
                  let last = values.count == 2 ? values[1] : firstValue,
                  first >= 1, last >= first, last <= count else { return nil }
            for page in first...last { pages.insert(page - 1) }
        }
        return pages.sorted()
    }

    private func updateCount() {
        countItem.title = selectedPages.isEmpty ? "尚未选择页面" : "已选 \(selectedPages.count) 页"
    }

    private func exportSelection() {
        let indexes = selectedPages.sorted()
        guard !indexes.isEmpty else {
            showMessage("尚未选择页面", detail: "先点选要保留的页面，或使用页码范围。")
            return
        }
        let result = PDFDocument()
        for index in indexes {
            if let page = session.document.page(at: index) { result.insert(page, at: result.pageCount) }
        }
        let output = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(sourceName)_节选_\(UUID().uuidString.prefix(6)).pdf")
        guard result.write(to: output) else {
            showMessage("导出失败", detail: "无法生成节选 PDF。")
            return
        }
        let picker = UIDocumentPickerViewController(forExporting: [output], asCopy: true)
        present(picker, animated: true)
    }

    private func showMessage(_ title: String, detail: String) {
        let alert = UIAlertController(title: title, message: detail, preferredStyle: .alert)
        alert.addAction(UIAlertAction(title: "好", style: .default))
        present(alert, animated: true)
    }
}

@MainActor
private final class ExtractPageCell: UICollectionViewCell {
    static let reuseID = "ExtractPageCell"
    private let imageView = UIImageView()
    private let pageLabel = UILabel()
    private let checkImage = UIImageView(image: UIImage(systemName: "checkmark.circle.fill"))
    private let backgroundCard = UIView()

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundCard.backgroundColor = .secondarySystemGroupedBackground
        backgroundCard.layer.cornerRadius = 18
        backgroundCard.layer.cornerCurve = .continuous
        backgroundCard.layer.borderWidth = 1
        backgroundCard.layer.borderColor = UIColor.separator.withAlphaComponent(0.25).cgColor
        backgroundCard.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(backgroundCard)
        NSLayoutConstraint.activate([
            backgroundCard.leadingAnchor.constraint(equalTo: contentView.leadingAnchor),
            backgroundCard.trailingAnchor.constraint(equalTo: contentView.trailingAnchor),
            backgroundCard.topAnchor.constraint(equalTo: contentView.topAnchor),
            backgroundCard.bottomAnchor.constraint(equalTo: contentView.bottomAnchor),
        ])
        imageView.contentMode = .scaleAspectFit
        imageView.backgroundColor = .systemBackground
        imageView.layer.cornerRadius = 10
        imageView.clipsToBounds = true
        imageView.translatesAutoresizingMaskIntoConstraints = false
        pageLabel.font = .systemFont(ofSize: 13, weight: .medium)
        pageLabel.textColor = .secondaryLabel
        checkImage.tintColor = .hiBrand
        checkImage.backgroundColor = .systemBackground
        checkImage.layer.cornerRadius = 12
        checkImage.translatesAutoresizingMaskIntoConstraints = false
        contentView.addSubview(imageView)
        contentView.addSubview(pageLabel)
        contentView.addSubview(checkImage)
        pageLabel.translatesAutoresizingMaskIntoConstraints = false
        NSLayoutConstraint.activate([
            imageView.leadingAnchor.constraint(equalTo: contentView.leadingAnchor, constant: 10),
            imageView.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -10),
            imageView.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 10),
            imageView.bottomAnchor.constraint(equalTo: pageLabel.topAnchor, constant: -6),
            pageLabel.centerXAnchor.constraint(equalTo: contentView.centerXAnchor),
            pageLabel.bottomAnchor.constraint(equalTo: contentView.bottomAnchor, constant: -8),
            checkImage.topAnchor.constraint(equalTo: contentView.topAnchor, constant: 14),
            checkImage.trailingAnchor.constraint(equalTo: contentView.trailingAnchor, constant: -14),
            checkImage.widthAnchor.constraint(equalToConstant: 24),
            checkImage.heightAnchor.constraint(equalToConstant: 24),
        ])
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    func configure(pageNumber: Int, thumbnail: UIImage?, selected: Bool) {
        imageView.image = thumbnail
        pageLabel.text = "第 \(pageNumber) 页"
        checkImage.isHidden = !selected
        backgroundCard.layer.borderColor = (selected ? UIColor.hiBrand : UIColor.separator.withAlphaComponent(0.25)).cgColor
        backgroundCard.layer.borderWidth = selected ? 2 : 1
        accessibilityLabel = "第 \(pageNumber) 页，\(selected ? "已选择" : "未选择")"
    }
}
