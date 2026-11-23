;;; rozpiska.lsp - vyplnenie rozpisky z registra vykresov
;;; AutoCAD 2020 a novsi (plna verzia).
;;;
;;; Prikazy:
;;;   ROZPISKA       nacita rozpiska.csv z registra a vyplni atributy rozpisky
;;;                  v layoutoch otvoreneho vykresu
;;;   ROZPISKA-TAGY  vypise bloky s atributmi v layoutoch (nazvy TAG a hodnoty)
;;;                  a ulozi ich do rozpiska-tagy.txt vedla DWG
;;;
;;; Postup:
;;;   1. V registri klikni na "Export pre rozpisku (AutoCAD)" -> rozpiska.csv
;;;   2. V AutoCADe: APPLOAD -> rozpiska.lsp (alebo pridaj do Startup Suite)
;;;   3. Otvor vykres a spusti ROZPISKA. Zmenu vratis prikazom U (spat).
;;;
;;; Vykres a layout sa paruju podla stlpcov DWG a LAYOUT z registra.
;;; Ked je v registri pri liste prazdny layout a DWG ma iba jeden layout,
;;; pouzije sa ten.
;;;
;;; Atributy v xref rozpiske sa upravit nedaju. Udaje zavisle od listu
;;; (cislo, nazov vykresu, mierka...) musia byt v lokalnom bloku v layoute.

(vl-load-com)

;;; ---------------------------------------------------------------------
;;; MAPOVANIE: stlpec z registra -> mozne nazvy TAG v rozpiske.
;;; Nazvy TAG sa porovnavaju bez diakritiky, medzier a znakov ako . _ -
;;; napr. "NAZOV_VYKRESU", "NAZOV VYKRESU" aj tag s diakritikou su to iste.
;;; Ak ma rozpiska iny TAG, dopis ho sem (velkymi pismenami, bez diakritiky).
;;; Stlpec, ktory tu nie je, sa vyplni do TAG s rovnakym nazvom.
;;; ---------------------------------------------------------------------
(setq *rozp-map*
  '(("CISLO_VYKRESU" "CISLOVYKRESU" "CVYKRESU" "CVYKR" "CVYK" "CISLOVYK" "CISLO")
    ("NAZOV_VYKRESU" "NAZOVVYKRESU" "NAZOVVYK" "NAZOV" "VYKRES")
    ("KOD"           "KOD" "PORTALCODE" "PORTALKOD" "KODPORTAL")
    ("STUPEN"        "STUPEN" "STUPENPD")
    ("CAST"          "CAST" "PROFESIA")
    ("REVIZIA"       "REVIZIA" "REV")
    ("OBJEKT"        "OBJEKT" "SO")
   )
)
;;; Stlpce, ktore sa nikdy nezapisuju (sluzia iba na parovanie).
(setq *rozp-skip* '("DWG" "LAYOUT"))

;;; --- diakritika: \U+XXXX zapis aj kody ANSI 1250 -----------------------
(setq *rozp-uni*
  '(("\\U+00C1" . "A") ("\\U+00C4" . "A") ("\\U+010C" . "C") ("\\U+010E" . "D")
    ("\\U+00C9" . "E") ("\\U+00CD" . "I") ("\\U+0139" . "L") ("\\U+013D" . "L")
    ("\\U+0147" . "N") ("\\U+00D3" . "O") ("\\U+00D4" . "O") ("\\U+0154" . "R")
    ("\\U+0160" . "S") ("\\U+0164" . "T") ("\\U+00DA" . "U") ("\\U+00DD" . "Y")
    ("\\U+017D" . "Z") ("\\U+00E1" . "A") ("\\U+00E4" . "A") ("\\U+010D" . "C")
    ("\\U+010F" . "D") ("\\U+00E9" . "E") ("\\U+00ED" . "I") ("\\U+013A" . "L")
    ("\\U+013E" . "L") ("\\U+0148" . "N") ("\\U+00F3" . "O") ("\\U+00F4" . "O")
    ("\\U+0155" . "R") ("\\U+0161" . "S") ("\\U+0165" . "T") ("\\U+00FA" . "U")
    ("\\U+00FD" . "Y") ("\\U+017E" . "Z") ("\\U+016F" . "U") ("\\U+011B" . "E")
    ("\\U+0159" . "R") ("\\U+011A" . "E") ("\\U+0158" . "R") ("\\U+016E" . "U")))
(setq *rozp-ansi*
  '((193 . "A") (196 . "A") (200 . "C") (207 . "D") (201 . "E") (205 . "I")
    (197 . "L") (188 . "L") (210 . "N") (211 . "O") (212 . "O") (192 . "R")
    (138 . "S") (141 . "T") (218 . "U") (221 . "Y") (142 . "Z") (225 . "A")
    (228 . "A") (232 . "C") (239 . "D") (233 . "E") (237 . "I") (229 . "L")
    (190 . "L") (242 . "N") (243 . "O") (244 . "O") (224 . "R") (154 . "S")
    (157 . "T") (250 . "U") (253 . "Y") (158 . "Z") (249 . "U") (236 . "E")
    (248 . "R") (204 . "E") (216 . "R") (217 . "U")))

(defun rozp:replace (s old new / p)
  (while (setq p (vl-string-search old s))
    (setq s (strcat (substr s 1 p) new (substr s (+ p 1 (strlen old))))))
  s)

;;; Porovnavaci kluc: velke pismena bez diakritiky, iba A-Z a 0-9.
(defun rozp:key (s / out i ch c tr)
  (setq s (strcase s))
  (foreach pair *rozp-uni* (setq s (rozp:replace s (car pair) (cdr pair))))
  (setq out "" i 1)
  (while (<= i (strlen s))
    (setq ch (substr s i 1) c (ascii ch))
    (cond ((or (and (>= c 48) (<= c 57)) (and (>= c 65) (<= c 90)))
           (setq out (strcat out ch)))
          ((setq tr (cdr (assoc c *rozp-ansi*))) (setq out (strcat out tr))))
    (setq i (1+ i)))
  out)

;;; --- CSV: oddelovac ; a texty v uvodzovkach ---------------------------
(defun rozp:parse (line / res cur inq i n ch)
  (setq res '() cur "" inq nil i 1 n (strlen line))
  (while (<= i n)
    (setq ch (substr line i 1))
    (cond ((and inq (= ch "\"") (= (substr line (1+ i) 1) "\""))
           (setq cur (strcat cur "\"") i (1+ i)))
          ((= ch "\"") (setq inq (not inq)))
          ((and (not inq) (= ch ";")) (setq res (cons cur res) cur ""))
          (t (setq cur (strcat cur ch))))
    (setq i (1+ i)))
  (reverse (cons cur res)))

;;; Vrati zoznam riadkov, kazdy ako ((STLPEC . hodnota) ...)
(defun rozp:read (path / f line head rows cells)
  (if (setq f (open path "r"))
    (progn
      (while (setq line (read-line f))
        (setq line (vl-string-right-trim "\r\n" line))
        (if (/= (vl-string-trim " \t" line) "")
          (progn
            (setq cells (rozp:parse line))
            (if head
              (setq rows (cons (mapcar 'cons head cells) rows))
              (setq head (mapcar 'strcase cells))))))
      (close f)))
  (if (and head (not (member "DWG" head)))
    (progn (princ "\nSubor nie je export pre rozpisku (chyba stlpec DWG).") nil)
    (reverse rows)))

(defun rozp:get (col row) (cond ((cdr (assoc col row))) ("")))

;;; Hodnota pre TAG podla mapovania, inak podla rovnakeho nazvu stlpca.
(defun rozp:value (tagkey row / hit)
  (foreach m *rozp-map*
    (if (and (not hit) (member tagkey (cdr m)) (assoc (car m) row))
      (setq hit (rozp:get (car m) row))))
  (if (not hit)
    (foreach cell row
      (if (and (not hit)
               (not (member (car cell) *rozp-skip*))
               (= (rozp:key (car cell)) tagkey))
        (setq hit (cdr cell)))))
  hit)

(defun rozp:paper-layouts (doc / out)
  (vlax-for lay (vla-get-Layouts doc)
    (if (/= (vla-get-ModelType lay) :vlax-true) (setq out (cons lay out))))
  (reverse out))

;;; Vyplni atributy vsetkych blokov v layoute. Vrati (pocet-atributov . tagy)
(defun rozp:fill-layout (lay row / n val tags)
  (setq n 0)
  (vlax-for obj (vla-get-Block lay)
    (if (and (= (vla-get-ObjectName obj) "AcDbBlockReference")
             (= (vla-get-HasAttributes obj) :vlax-true))
      (foreach att (vlax-invoke obj 'GetAttributes)
        (if (setq val (rozp:value (rozp:key (vla-get-TagString att)) row))
          (progn
            (if (/= (vla-get-TextString att) val)
              (vla-put-TextString att val))
            (setq n (1+ n) tags (cons (vla-get-TagString att) tags)))))))
  (cons n (reverse tags)))

(defun rozp:pick-csv (/ last dir path)
  (setq last (getenv "ROZPISKA_CSV"))
  (setq dir (if (and last (findfile last)) last "rozpiska.csv"))
  (setq path (getfiled "Vyber rozpiska.csv z registra vykresov" dir "csv" 0))
  (if path (setenv "ROZPISKA_CSV" path))
  path)

(defun c:ROZPISKA (/ doc path rows mine lays row res total done missing)
  (setq doc (vla-get-ActiveDocument (vlax-get-acad-object)))
  (if (and (setq path (rozp:pick-csv)) (setq rows (rozp:read path)))
    (progn
      (foreach r rows
        (if (= (rozp:key (vl-filename-base (rozp:get "DWG" r))) (rozp:key (vl-filename-base (getvar "DWGNAME"))))
          (setq mine (cons r mine))))
      (setq mine (reverse mine) lays (rozp:paper-layouts doc) total 0 done 0)
      (if (not mine)
        (princ (strcat "\nV registri nie je ziadny list pre " (getvar "DWGNAME")
                       ".\nV registri dopln pri liste skutocny DWG / layout a exportuj znova."))
        (progn
          (vla-StartUndoMark doc)
          (foreach lay lays
            (setq row nil)
            (foreach r mine
              (if (and (not row)
                       (/= (rozp:get "LAYOUT" r) "")
                       (= (rozp:key (rozp:get "LAYOUT" r)) (rozp:key (vla-get-Name lay))))
                (setq row r)))
            (if (and (not row) (= (length lays) 1) (= (length mine) 1))
              (setq row (car mine)))
            (if row
              (progn
                (setq res (rozp:fill-layout lay row) done (1+ done) total (+ total (car res)))
                (princ (strcat "\n  " (vla-get-Name lay) ": " (itoa (car res)) " atributov"
                               (if (cdr res) (strcat " (" (rozp:join (cdr res) ", ") ")") " - ziadny TAG nesedi, spusti ROZPISKA-TAGY"))))
              (setq missing (cons (vla-get-Name lay) missing))))
          (vla-EndUndoMark doc)
          (vla-Regen doc acAllViewports)
          (princ (strcat "\nHotovo: " (itoa done) " layoutov, " (itoa total) " atributov."))
          (if missing
            (princ (strcat "\nBez zaznamu v registri: " (rozp:join (reverse missing) ", ")))))))
  )
  (princ))

(defun rozp:join (lst sep / out)
  (setq out "")
  (foreach s lst (setq out (if (= out "") s (strcat out sep s))))
  out)

(defun c:ROZPISKA-TAGY (/ doc blocks lines out f line bname)
  (setq doc (vla-get-ActiveDocument (vlax-get-acad-object))
        blocks (vla-get-Blocks doc))
  (setq lines (list (strcat "Vykres: " (getvar "DWGPREFIX") (getvar "DWGNAME"))))
  (vlax-for lay (vla-get-Layouts doc)
    (vlax-for obj (vla-get-Block lay)
      (if (= (vla-get-ObjectName obj) "AcDbBlockReference")
        (progn
          (setq bname (vla-get-Name obj))
          (cond
            ((= (vla-get-IsXRef (vla-item blocks bname)) :vlax-true)
             (setq lines (cons (strcat "[" (vla-get-Name lay) "] XREF " bname
                                       " - atributy v xref sa z vykresu upravit nedaju")
                               lines)))
            ((= (vla-get-HasAttributes obj) :vlax-true)
             (setq lines (cons (strcat "[" (vla-get-Name lay) "] BLOK " (vla-get-EffectiveName obj)) lines))
             (foreach att (vlax-invoke obj 'GetAttributes)
               (setq line (strcat "    " (vla-get-TagString att) " = " (vla-get-TextString att)))
               (if (rozp:value (rozp:key (vla-get-TagString att))
                               (mapcar '(lambda (m) (cons (car m) "x")) *rozp-map*))
                 (setq line (strcat line "   <- vyplni ROZPISKA")))
               (setq lines (cons line lines)))))))))
  (setq lines (reverse lines))
  (foreach l lines (princ (strcat "\n" l)))
  (setq out (strcat (getvar "DWGPREFIX") "rozpiska-tagy.txt"))
  (if (setq f (open out "w"))
    (progn (foreach l lines (write-line l f)) (close f)
           (princ (strcat "\n\nUlozene do " out))))
  (princ))

(princ "\nRozpiska nacitana. Prikazy: ROZPISKA, ROZPISKA-TAGY")
(princ)
