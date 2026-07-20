using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace AssistantDocumentaire1.Migrations
{
    /// <inheritdoc />
    public partial class AjoutTailleDocument : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.AddColumn<long>(
                name: "TailleOctets",
                table: "Documents",
                type: "bigint",
                nullable: false,
                defaultValue: 0L);
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropColumn(
                name: "TailleOctets",
                table: "Documents");
        }
    }
}
