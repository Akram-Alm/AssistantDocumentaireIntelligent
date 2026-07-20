namespace AssistantDocumentaire1.Models
{
    public class Document
    {
        public int Id { get; set; }
        public long TailleOctets { get; set; }
        public string Titre { get; set; } = string.Empty;
        public DateTime DateAjout { get; set; } = DateTime.Now;
        public string Chemin { get; set; } = string.Empty;
        public bool EstIndexe { get; set; } = false;
    }
}