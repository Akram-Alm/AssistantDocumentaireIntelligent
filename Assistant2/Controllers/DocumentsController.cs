using AssistantDocumentaire1.Models;
using AssistantDocumentaire1.Data;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using System.Text;
using System.Text.Json;

namespace AssistantDocumentaire1.Controllers
{
    public class DocumentsController : Controller
    {
        private readonly ApplicationDbContext _context;
        private readonly IWebHostEnvironment _environment;
        private readonly IHttpClientFactory _httpClientFactory;
        private readonly string _ragServiceUrl;
        private readonly IConfiguration _configuration;

        public DocumentsController(ApplicationDbContext context, IWebHostEnvironment environment, IHttpClientFactory httpClientFactory, IConfiguration configuration)
        {
            _context = context;
            _environment = environment;
            _httpClientFactory = httpClientFactory;
            _configuration = configuration;
            _ragServiceUrl = configuration["RagServiceUrl"] ?? "http://127.0.0.1:8001";
        }

        public async Task<IActionResult> Index()
        {
            var documents = await _context.Documents
                .OrderByDescending(d => d.DateAjout)
                .ToListAsync();
            return View(documents);
        }

        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Upload(List<IFormFile> fichiers)
        {
            if (fichiers == null || fichiers.Count == 0)
            {
                return RedirectToAction(nameof(Index));
            }

            string dossierStockage = _configuration["StoragePath"] ?? Path.Combine(_environment.ContentRootPath, "UploadedFiles");
            if (!Directory.Exists(dossierStockage))
            {
                Directory.CreateDirectory(dossierStockage);
            }

            var nouveauxDocuments = new List<Document>();

            foreach (var fichier in fichiers)
            {
                if (fichier.Length == 0 || Path.GetExtension(fichier.FileName).ToLower() != ".pdf")
                {
                    continue;
                }

                string nomUnique = $"{Guid.NewGuid()}_{fichier.FileName}";
                string cheminComplet = Path.Combine(dossierStockage, nomUnique);

                using (var stream = new FileStream(cheminComplet, FileMode.Create))
                {
                    await fichier.CopyToAsync(stream);
                }

                var document = new Document
                {
                    Titre = fichier.FileName,
                    DateAjout = DateTime.Now,
                    Chemin = cheminComplet,
                    TailleOctets = fichier.Length,
                    EstIndexe = false
                };

                _context.Documents.Add(document);
                nouveauxDocuments.Add(document);
            }

            await _context.SaveChangesAsync(); // sauvegarde d'abord pour obtenir les Id

            // Indexation automatique dans le service Python RAG
            foreach (var document in nouveauxDocuments)
            {
                bool succes = await IndexerDansRagAsync(document);
                document.EstIndexe = succes;
            }

            await _context.SaveChangesAsync(); // met à jour EstIndexe

            return RedirectToAction(nameof(Index));
        }

        private async Task<bool> IndexerDansRagAsync(Document document)
        {
            try
            {
                var client = _httpClientFactory.CreateClient();
                var contenu = new StringContent(
                    JsonSerializer.Serialize(new { chemin = document.Chemin, titre = document.Titre, document_id = document.Id }),
                    Encoding.UTF8,
                    "application/json");

                var reponse = await client.PostAsync($"{_ragServiceUrl}/index", contenu);
                return reponse.IsSuccessStatusCode;
            }
            catch (HttpRequestException)
            {
                return false;
            }
        }

        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Supprimer(int id)
        {
            var document = await _context.Documents.FindAsync(id);
            if (document != null)
            {
                // 1. Prévenir le service Python pour retirer les chunks de FAISS
                try
                {
                    var client = _httpClientFactory.CreateClient();
                    var contenu = new StringContent(
                        JsonSerializer.Serialize(new { document_id = document.Id }),
                        Encoding.UTF8,
                        "application/json");
                    await client.PostAsync($"{_ragServiceUrl}/supprimer", contenu);
                }
                catch (HttpRequestException)
                {
                    // Le service Python n'est peut-être pas lancé, on continue quand même la suppression locale
                }

                // 2. Supprimer le fichier physique
                if (System.IO.File.Exists(document.Chemin))
                {
                    System.IO.File.Delete(document.Chemin);
                }

                // 3. Supprimer la ligne SQL
                _context.Documents.Remove(document);
                await _context.SaveChangesAsync();
            }
            return RedirectToAction(nameof(Index));
        }

        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> ReindexerTout()
        {
            var documents = await _context.Documents.ToListAsync();

            var client = _httpClientFactory.CreateClient();
            client.Timeout = TimeSpan.FromMinutes(5); // peut être long si beaucoup de documents

            var payload = new
            {
                documents = documents.Select(d => new { document_id = d.Id, chemin = d.Chemin, titre = d.Titre })
            };

            try
            {
                var contenu = new StringContent(JsonSerializer.Serialize(payload), Encoding.UTF8, "application/json");
                var reponseHttp = await client.PostAsync($"{_ragServiceUrl}/reindexer_tout", contenu);

                if (reponseHttp.IsSuccessStatusCode)
                {
                    foreach (var doc in documents)
                    {
                        doc.EstIndexe = true;
                    }
                    await _context.SaveChangesAsync();
                    TempData["Succes"] = $"{documents.Count} document(s) ré-indexé(s) avec succès.";
                }
                else
                {
                    TempData["Erreur"] = "Le service Python a renvoyé une erreur lors de la ré-indexation.";
                }
            }
            catch (HttpRequestException)
            {
                TempData["Erreur"] = "Impossible de contacter le service Python. Vérifie qu'il tourne sur le port 8001.";
            }
            catch (TaskCanceledException)
            {
                TempData["Erreur"] = "La ré-indexation prend trop de temps (timeout de 5 minutes dépassé).";
            }

            return RedirectToAction(nameof(Index));
        }

        public class RenommerRequest
        {
            public int Id { get; set; }
            public string NouveauTitre { get; set; } = string.Empty;
        }

        [HttpPost]
        public async Task<IActionResult> Renommer([FromBody] RenommerRequest req)
        {
            var document = await _context.Documents.FindAsync(req.Id);
            if (document != null)
            {
                document.Titre = req.NouveauTitre;
                await _context.SaveChangesAsync();
            }
            return Ok();
        }
    }
}